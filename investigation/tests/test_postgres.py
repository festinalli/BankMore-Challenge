"""Opt-in PostgreSQL/pgvector integration; requires a disposable test database."""
import os
import uuid

import pytest
from sqlalchemy import text

from bankmore_intelligence.config import Settings
from bankmore_intelligence.db import database, migrate
from bankmore_intelligence.demo import seed
from bankmore_intelligence.rag import search, seed_documents
from bankmore_intelligence.service import Investigation


@pytest.mark.skipif(not os.getenv('INTELLIGENCE_TEST_POSTGRES_URL'), reason='PostgreSQL de teste não configurado')
def test_postgres_vector_and_case_roundtrip():
    url = os.environ['INTELLIGENCE_TEST_POSTGRES_URL']
    admin = database(url)
    schema = 'fi_test_' + uuid.uuid4().hex
    with admin.begin() as conn:
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    from sqlalchemy import create_engine
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema},public'},
        execution_options={'schema_translate_map': {None: schema}})
    try:
        migrate(engine)
        settings = Settings(database_url=url, pseudonym_key='k'*40, mode='demo')
        class Embeddings:
            def embed(self, texts): return [[1.0, float(index + 1), 0.5] for index, _ in enumerate(texts)]
        seed_documents(engine, settings, Embeddings())
        result = search(engine, settings, 'burst', '2026-09-01T00:00:00+00:00', 'operacoes', embedder=Embeddings())
        assert result['mode'] == 'hybrid-rrf'
        assert result['documents']
        service = Investigation(engine, settings)
        ids = seed(service)
        identity = {'subject': 'test', 'queue': 'operacoes'}
        report = service.draft(ids['suspeita'], 1, identity)
        assert report['content']['proposal']['recomendacao'] == 'INVESTIGAR'
        assert seed(service) == ids
    finally:
        engine.dispose()
        with admin.begin() as conn:
            # Only the exact random schema created by this test is removed.
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()
