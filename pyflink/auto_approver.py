"""
Auto-approver temporário do Sprint 1.

Função: enquanto o PyFlink real não está pronto (Sprint 2), este script consome
`transferencia.solicitada` e republica em `transferencia.aprovada` sem análise
de fraude. Serve apenas para validar o fluxo end-to-end:

    Frontend → Transferencia.Api → Kafka(solicitada) → [este] → Kafka(aprovada) → Worker → Postgres

Substituir pelo job PyFlink no Sprint 2.

Uso (local, fora do compose):
    pip install confluent-kafka
    python auto_approver.py

Uso (dentro do compose):
    Será dockerizado em infra/compose/docker-compose.yml na próxima iteração.
"""

import json
import logging
import os
import signal
import sys
from confluent_kafka import Consumer, Producer, KafkaError

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:9092")
SOURCE_TOPIC  = os.getenv("SOURCE_TOPIC",  "transferencia.solicitada")
SINK_TOPIC    = os.getenv("SINK_TOPIC",    "transferencia.aprovada")
GROUP_ID      = os.getenv("GROUP_ID",      "auto-approver")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("auto-approver")

_shutdown = False
def _on_signal(signum, frame):
    global _shutdown
    log.info(f"Sinal {signum} recebido — encerrando...")
    _shutdown = True

signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


def main():
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    producer = Producer({"bootstrap.servers": KAFKA_BROKERS, "acks": "all"})

    consumer.subscribe([SOURCE_TOPIC])
    log.info(f"Aguardando mensagens em '{SOURCE_TOPIC}' → '{SINK_TOPIC}' (brokers={KAFKA_BROKERS})")

    try:
        while not _shutdown:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error(f"Kafka error: {msg.error()}")
                continue

            try:
                payload = json.loads(msg.value().decode("utf-8"))
            except Exception as e:
                log.error(f"JSON inválido: {e}")
                continue

            # NO-OP de aprovação — Sprint 2 substitui isso pelo Flink com scoring real
            log.info(f"Auto-aprovando id={payload.get('Id') or payload.get('id')} "
                     f"valor={payload.get('Valor') or payload.get('valor')}")

            producer.produce(
                topic=SINK_TOPIC,
                key=msg.key(),
                value=json.dumps(payload).encode("utf-8"),
            )
            producer.poll(0)

        producer.flush(timeout=10)
    finally:
        consumer.close()
        log.info("Encerrado.")


if __name__ == "__main__":
    sys.exit(main() or 0)
