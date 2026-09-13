"""Real Kafka -> consumer -> isolated PostgreSQL database -> authenticated API.

Run only against the private broker in compose.integration.yml. The script creates
and drops its own randomly named database; it never deletes the configured database.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
from confluent_kafka import Consumer, Producer, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from bankmore_intelligence.config import Settings
from bankmore_intelligence.db import cases, database, events, migrate, quarantine
from bankmore_intelligence.rag import seed_documents
from bankmore_intelligence.service import TOPICS


def eventually(check, label, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.2)
    raise AssertionError('Timeout: ' + label)


def main():
    if os.environ['KAFKA_BROKERS'] != 'intelligence-kafka:9092':
        raise RuntimeError('Este teste exige o broker isolado do compose.integration.yml')
    base_url = make_url(os.environ['INTELLIGENCE_DATABASE_URL'])
    test_name = 'fi_kafka_' + uuid.uuid4().hex
    admin_db = database(base_url.render_as_string(hide_password=False))
    engine = None
    processes = []
    cursor = None
    with tempfile.TemporaryFile(mode='w+') as logs:
        try:
            with admin_db.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
                conn.execute(text(f'CREATE DATABASE {test_name}'))
            test_url = base_url.set(database=test_name).render_as_string(hide_password=False)
            engine = database(test_url)
            migrate(engine)
            settings = Settings(database_url=test_url, mode='demo')
            seed_documents(engine, settings)
            broker = os.environ['KAFKA_BROKERS']
            kafka_admin = AdminClient({'bootstrap.servers': broker})
            for future in kafka_admin.create_topics([NewTopic(t, 1, 1) for t in sorted(TOPICS)]).values():
                try:
                    future.result(timeout=30)
                except Exception as error:
                    if 'TOPIC_ALREADY_EXISTS' not in str(error):
                        raise
            env = {**os.environ, 'INTELLIGENCE_DATABASE_URL': test_url, 'INTELLIGENCE_MODE': 'demo'}

            def start(module, *args):
                child = subprocess.Popen([sys.executable, '-m', module, *args], env=env, stdout=logs, stderr=logs)
                processes.append(child)
                return child

            worker = start('bankmore_intelligence.consumer')
            producer = Producer({'bootstrap.servers': broker, 'acks': 'all', 'enable.idempotence': True})
            cursor = Consumer({'bootstrap.servers': broker, 'group.id': 'bankmore-investigation-v1',
                               'enable.auto.commit': False})

            def publish(topic, payload):
                delivered = []
                producer.produce(topic, value=json.dumps(payload).encode() if isinstance(payload, dict) else payload,
                    on_delivery=lambda error, message: delivered.append((error, message.offset())))
                assert producer.flush(15) == 0
                assert delivered and delivered[0][0] is None, 'Broker did not acknowledge event'
                return delivered[0][1]

            def committed(topic, offset):
                assert worker.poll() is None, 'Consumer exited before durable processing'
                return cursor.committed([TopicPartition(topic, 0)], timeout=5)[0].offset >= offset + 1

            def count(table):
                with engine.connect() as conn:
                    return conn.execute(select(func.count()).select_from(table)).scalar_one()

            prefix = uuid.uuid4().hex
            event = {'id': prefix + '-history', 'cpfOrigem': '00000000009', 'valor': 900,
                     'tipo': 'TED', 'timestamp': 1788263940000, 'decididoEm': 1788263940000,
                     'decisao': 'APROVADA', 'motivos': [], 'modeloVersao': 'synthetic-kafka-test-v1'}
            offset = publish('transferencia.aprovada', event)
            eventually(lambda: committed('transferencia.aprovada', offset), 'history offset')
            assert count(events) == 1
            event.update(id=prefix + '-alert', timestamp=1788264000000, decididoEm=1788264000000,
                         decisao='REJEITADA', motivos=['BURST_4_EM_60s'])
            publish('transferencia.rejeitada', event)
            offset = publish('transferencia.rejeitada', event)
            eventually(lambda: committed('transferencia.rejeitada', offset), 'duplicate offset')
            assert count(cases) == 1 and count(events) == 2
            with engine.connect() as conn:
                case = conn.execute(select(cases)).mappings().one()
                case_id = case['id']
                assert case['snapshot']['summary']['previous_count_24h'] == 1
            publish('transferencia.rejeitada', b'{invalid json')
            conflict = {**event, 'valor': 999}
            offset = publish('transferencia.rejeitada', conflict)
            eventually(lambda: committed('transferencia.rejeitada', offset), 'quarantine offset')
            assert count(quarantine) == 2 and count(cases) == 1

            worker.terminate()
            worker.wait(timeout=15)
            worker = start('bankmore_intelligence.consumer')
            publish('transferencia.rejeitada', event)
            offset = publish('transferencia.rejeitada', {**event, 'id': prefix + '-after-restart'})
            eventually(lambda: committed('transferencia.rejeitada', offset), 'restart offset')
            assert count(cases) == 2 and count(events) == 3
            assert count(quarantine) == 2

            api = start('bankmore_intelligence', 'serve', '--port', '5019')
            with httpx.Client(base_url='http://127.0.0.1:5019', trust_env=False, timeout=15) as client:
                def healthy():
                    assert api.poll() is None, 'API exited'
                    try:
                        return client.get('/health').status_code == 200
                    except httpx.TransportError:
                        return False
                eventually(healthy, 'API readiness')
                token = next(t for t, identity in settings.identities.items()
                             if 'draft' in identity['scopes'] and 'review' not in identity['scopes'])
                headers = {'Authorization': 'Bearer ' + token}
                result = client.post(f'/api/cases/{case_id}/reports', headers=headers, json={'expected_version': 1})
                assert result.status_code == 200, 'Report request failed'
                report = result.json()
                assert report['content']['proposal']['recomendacao'] == 'INVESTIGAR'
                assert client.get(f'/api/cases/{case_id}', headers=headers).json()['reports'][0]['id'] == report['id']
                denied = client.post(f'/api/cases/{case_id}/reviews', headers=headers, json={
                    'report_id': report['id'], 'expected_version': 2, 'outcome': 'INCONCLUSIVO',
                    'rationale': 'Synthetic integration test only.'})
                assert denied.status_code == 403
            print(json.dumps({'result': 'passed', 'checks': [
                'kafka_delivery', 'postgres_snapshot', 'deduplication', 'durable_offsets',
                'invalid_and_conflicting_event_quarantine', 'consumer_restart',
                'authenticated_report_api', 'assistant_cannot_review']}))
        except Exception:
            logs.seek(0)
            # Logs may include URLs in database errors: redact the configured password.
            safe_log = logs.read().replace(base_url.password or 'PASSWORD_UNSET', '[redacted]')
            print(safe_log[-6000:], file=sys.stderr)
            raise
        finally:
            for child in processes:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=15)
            if cursor:
                cursor.close()
            if engine:
                engine.dispose()
            with admin_db.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS {test_name}'))
            admin_db.dispose()


if __name__ == '__main__':
    main()
