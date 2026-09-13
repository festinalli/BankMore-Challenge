from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, Float, Integer, MetaData, Numeric, String, Table, Text, create_engine, event, text
from sqlalchemy.pool import StaticPool

metadata = MetaData()
events = Table("fi_events", metadata,
    Column("event_key", String(64), primary_key=True), Column("digest", String(64), nullable=False),
    Column("queue", String(50), nullable=False), Column("transaction_id", String(100), nullable=False),
    Column("customer", String(64), nullable=False, index=True), Column("topic", String(100), nullable=False),
    Column("occurred_ms", Float, nullable=False, index=True), Column("amount", Numeric(18, 2), nullable=False),
    Column("payload", JSON, nullable=False), Column("received_at", String(40), nullable=False))
cases = Table("fi_cases", metadata,
    Column("id", String(64), primary_key=True), Column("queue", String(50), nullable=False, index=True),
    Column("status", String(30), nullable=False), Column("version", Integer, nullable=False),
    Column("snapshot", JSON, nullable=False), Column("created_at", String(40), nullable=False))
reports = Table("fi_reports", metadata,
    Column("id", String(64), primary_key=True), Column("case_id", String(64), nullable=False, index=True),
    Column("snapshot_hash", String(64), nullable=False), Column("content", JSON, nullable=False),
    Column("created_at", String(40), nullable=False))
reviews = Table("fi_reviews", metadata,
    Column("id", String(64), primary_key=True), Column("case_id", String(64), nullable=False, unique=True),
    Column("report_id", String(64), nullable=False), Column("subject", String(100), nullable=False),
    Column("outcome", String(30), nullable=False), Column("rationale", Text, nullable=False),
    Column("created_at", String(40), nullable=False))
documents = Table("fi_documents", metadata,
    Column("id", String(100), primary_key=True), Column("queue", String(50), nullable=False),
    Column("title", Text, nullable=False), Column("body", Text, nullable=False),
    Column("valid_from", String(40), nullable=False), Column("valid_to", String(40)),
    Column("digest", String(64), nullable=False), Column("embedding_model", String(100)),
    Column("embedding", Vector().with_variant(JSON(), "sqlite")))
audit = Table("fi_audit", metadata,
    Column("id", String(64), primary_key=True), Column("subject", String(100), nullable=False),
    Column("action", String(100), nullable=False), Column("case_id", String(64)),
    Column("details", JSON, nullable=False), Column("created_at", String(40), nullable=False))
quarantine = Table("fi_quarantine", metadata,
    Column("id", String(150), primary_key=True), Column("reason", String(100), nullable=False),
    Column("digest", String(64), nullable=False), Column("created_at", String(40), nullable=False))


def now():
    return datetime.now(timezone.utc).isoformat()


def database(url):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def sqlite_options(connection, _):
            connection.execute("PRAGMA journal_mode=WAL")
    return engine


def migrate(engine):
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(198221)"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        metadata.create_all(conn)
