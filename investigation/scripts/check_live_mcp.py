"""Actual local .NET -> Kafka -> PyFlink/XGBoost -> PostgreSQL -> MCP -> Ollama.

Creates NEW fictitious accounts in the isolated bankmore-live project only.
Does not publish detector output, seed investigation cases, or simulate a score.
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid

import httpx
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
API = 'http://127.0.0.1:5010'
ACCOUNTS = 'http://127.0.0.1:5100/api/contacorrente'
TRANSFERS = 'http://127.0.0.1:5101/api/transferencia/efetuar'


def sql_transfer(transaction_id):
    transaction_id = str(uuid.UUID(transaction_id))
    query = "SELECT json_build_object('status',status,'reason',motivo,'score',score_fraude,'model',modelo_versao,'movements',(SELECT count(*) FROM movimento WHERE transferencia_id=t.id)) FROM transferencia t WHERE id='" + transaction_id + "'"
    return json.loads(subprocess.check_output(['docker', 'exec', 'bankmore-live-postgres-1',
        'psql', '-U', 'bankmore', '-d', 'bankmore_live', '-At', '-c', query], text=True))


def fictional_cpf():
    digits = [secrets.randbelow(10) for _ in range(9)]
    for length in (9, 10):
        value = 11 - sum(v * (length + 1 - i) for i, v in enumerate(digits)) % 11
        digits.append(0 if value >= 10 else value)
    return ''.join(map(str, digits))


def create_account(client, label):
    cpf, password = fictional_cpf(), secrets.token_urlsafe(24)
    response = client.post(ACCOUNTS + '/criar', json={'nome': 'Simulacao local ' + label,
        'cpf': cpf, 'senha': password, 'saldoInicial': 100000})
    response.raise_for_status()
    response = client.post(ACCOUNTS + '/login', json={'cpf': cpf, 'senha': password})
    response.raise_for_status()
    return cpf, response.json()['token']


async def main():
    for name in ('postgres', 'contacorrente-api', 'transferencia-api'):
        project = subprocess.check_output(['docker', 'inspect', f'bankmore-live-{name}-1',
            '--format', '{{index .Config.Labels "com.docker.compose.project"}}'], text=True).strip()
        if project != 'bankmore-live':
            raise RuntimeError('This script only supports the isolated bankmore-live project')
    config = dotenv_values(ROOT / 'investigation/.env.local')
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'investigation'),
        'INTELLIGENCE_API_URL': API, 'INTELLIGENCE_MCP_TOKEN': config['INTELLIGENCE_MCP_TOKEN']}
    headers = {'Authorization': 'Bearer ' + config['INTELLIGENCE_MCP_TOKEN']}
    with httpx.Client(trust_env=False, timeout=30) as client:
        assert client.get(API+'/health').json()['mode'] == 'ollama'
        destination, _ = create_account(client, 'destino')
        _, normal_token = create_account(client, 'controle')
        _, suspicious_token = create_account(client, 'sinal ML')

        def transfer(token, amount):
            response = client.post(TRANSFERS, headers={'Authorization': 'Bearer '+token},
                json={'cpfDestino': destination, 'valor': amount, 'tipo': 'TED'})
            response.raise_for_status()
            assert response.status_code == 202
            return response.json()['id']

        normal_id = transfer(normal_token, 200)
        suspicious_id = transfer(suspicious_token, 30000)
        print('Transferencias enviadas pelas APIs .NET; aguardando detector real.', flush=True)
        params = StdioServerParameters(command=sys.executable,
            args=['-m','bankmore_intelligence.mcp_server'], env=env, cwd=str(ROOT))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert len(names) == 6 and not any('revisao' in n for n in names)

                async def call(name, args):
                    result = await session.call_tool(name, args)
                    if result.isError:
                        raise AssertionError(str(result.content))
                    data = result.structuredContent
                    if data is None:
                        if name == 'listar_alertas':
                            return [json.loads(block.text) for block in result.content]
                        data = json.loads(result.content[0].text)
                    return data.get('result', data) if isinstance(data, dict) else data

                started = time.monotonic()
                found = None
                while time.monotonic() - started < 240:
                    items = await call('listar_alertas', {'limit':50})
                    found = next((item for item in items if item['event']['id'] == suspicious_id), None)
                    if found:
                        break
                    await asyncio.sleep(3)
                if found is None:
                    raise AssertionError('Detector alert did not reach MCP within 240 seconds')
                case_id = found['id']
                detail = await call('obter_evidencias_caso', {'case_id':case_id})
                event = detail['snapshot']['event']
                assert event['id'] == suspicious_id and not event['synthetic']
                assert event['scoreFraude'] >= .95 and 'xgboost' in event['modeloVersao']
                assert any(reason.startswith('ML_SCORE_') for reason in event['motivos'])
                assert 'cpfOrigem' not in event and len(event['customer']) == 64
                print('Alerta real encontrado pelo MCP; score e versao do XGBoost preservados.', flush=True)
                await call('obter_resumo_comportamental', {'case_id':case_id})
                procedures = await call('buscar_procedimentos', {'case_id':case_id,'query':'score alto evidencias contexto'})
                assert procedures['documents']
                await call('buscar_casos_revisados', {'case_id':case_id})
                report = await call('registrar_parecer', {'case_id':case_id,'expected_version':detail['version']})
                content = report['content']
                assert content['generation']['mode'] == 'ollama', 'Real inference required; fallback is not a passing result'
                assert content['retrieval']['mode'] == 'hybrid-rrf'
                persisted = await call('obter_evidencias_caso', {'case_id':case_id})
                assert persisted['reports'][0]['id'] == report['id']
                response = client.post(API+f'/api/cases/{case_id}/reviews', headers=headers,
                    json={'report_id':report['id'],'expected_version':persisted['version'],
                          'outcome':'FRAUDE_CONFIRMADA','rationale':'Permission negative test; must never be persisted.'})
                assert response.status_code == 403
                normal, rejected = sql_transfer(normal_id), sql_transfer(suspicious_id)
                assert normal['status'] == 'EFETIVADA' and normal['movements'] >= 2, normal
                assert rejected['status'] == 'REJEITADA' and rejected['movements'] == 0, rejected
                evidence = {'status':'passed','environment':'isolated local simulation with fictitious accounts',
                    'transport':'JSON','normal_transaction':{'id':normal_id,**normal},
                    'flagged_transaction':{'id':suspicious_id,**rejected},'case_id':case_id,
                    'mcp_tools':sorted(names),'report_id':report['id'],
                    'generation':content['generation'],'retrieval_mode':content['retrieval']['mode'],
                    'recommendation':content['proposal']['recomendacao'],'latency_ms':content['latency_ms'],
                    'assistant_review_http_status':403}
                (ROOT/'investigation/live-evidence.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False),encoding='utf-8')
                print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    asyncio.run(main())
