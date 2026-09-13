import hashlib
import json
import logging
import os
import signal

from confluent_kafka import Consumer, KafkaException
from sqlalchemy import select

from .config import Settings
from .db import database, migrate, now, quarantine
from .service import Investigation, TOPICS

log = logging.getLogger(__name__)


def process_message(service, message):
    """Commit Kafka only after a durable snapshot or a durable quarantine record."""
    raw = message.value() or b""
    try:
        if len(raw) > 65536:
            raise ValueError("Evento excede 64 KiB")
        service.ingest(json.loads(raw), message.topic())
        return "persisted"
    except (ValueError, TypeError):
        # Raw payload may contain CPF. Keep a hash and Kafka coordinates, never the raw body.
        key = f"{message.topic()}:{message.partition()}:{message.offset()}"
        with service.engine.begin() as conn:
            if not conn.execute(select(quarantine.c.id).where(quarantine.c.id == key)).first():
                conn.execute(quarantine.insert().values(id=key, reason="INVALID_OR_CONFLICTING_EVENT",
                    digest=hashlib.sha256(raw).hexdigest(), created_at=now()))
        log.warning("Evento em quarentena: %s", key)
        return "quarantined"


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    settings.validate()
    engine = database(settings.database_url)
    migrate(engine)
    service = Investigation(engine, settings)
    consumer = Consumer({"bootstrap.servers": os.environ["KAFKA_BROKERS"],
        "group.id": "bankmore-investigation-v1", "enable.auto.commit": False,
        "enable.auto.offset.store": False, "auto.offset.reset": "earliest"})
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    consumer.subscribe(sorted(TOPICS))
    try:
        while running:
            message = consumer.poll(1)
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())
            process_message(service, message)
            consumer.commit(message=message, asynchronous=False)
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
