"""Real SDK client -> stdio server -> authenticated HTTP API, all on loopback."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bankmore_intelligence.config import Settings
from bankmore_intelligence.db import database, migrate
from bankmore_intelligence.demo import seed
from bankmore_intelligence.rag import seed_documents
from bankmore_intelligence.service import Investigation


def test_stdio_to_authenticated_api(tmp_path):
    token = 'protocol-test-token-' * 3
    identities = {token: {'subject': 'mcp-test', 'queue': 'operacoes', 'scopes': ['read', 'draft']}}
    root = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'protocol.db'}"
    settings = Settings(database_url=url, identities=identities, pseudonym_key='z'*40, mode='demo')
    engine = database(url)
    migrate(engine)
    seed_documents(engine, settings)
    ids = seed(Investigation(engine, settings))
    engine.dispose()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'PYTHONPATH': str(root), 'INTELLIGENCE_MODE': 'demo',
        'INTELLIGENCE_DATABASE_URL': url, 'INTELLIGENCE_PSEUDONYM_KEY': 'z'*40,
        'INTELLIGENCE_IDENTITIES': json.dumps(identities), 'INTELLIGENCE_MCP_TOKEN': token,
        'INTELLIGENCE_API_URL': f'http://127.0.0.1:{port}'}
    process = subprocess.Popen([sys.executable, '-m', 'bankmore_intelligence', 'serve', '--port', str(port)],
        cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get(env['INTELLIGENCE_API_URL']+'/health').is_success:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError('API did not start')

        async def exercise():
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'bankmore_intelligence.mcp_server'], env=env, cwd=str(root))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert len((await session.list_tools()).tools) == 6
                    for name, args in [
                        ('listar_alertas', {}), ('obter_evidencias_caso', {'case_id': ids['suspeita']}),
                        ('obter_resumo_comportamental', {'case_id': ids['suspeita']}),
                        ('buscar_procedimentos', {'case_id': ids['suspeita'], 'query': 'burst'}),
                        ('buscar_casos_revisados', {'case_id': ids['suspeita']}),
                        ('registrar_parecer', {'case_id': ids['suspeita'], 'expected_version': 1})]:
                        result = await session.call_tool(name, args)
                        assert not result.isError, result
                    invalid = await session.call_tool('registrar_parecer', {'case_id': ids['suspeita'], 'expected_version': 1})
                    assert invalid.isError
        asyncio.run(exercise())
    finally:
        process.terminate()
        process.wait(timeout=10)
