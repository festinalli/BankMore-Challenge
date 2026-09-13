"""Evaluate three synthetic cases with real local Ollama inference.
Run from repository root: python investigation/scripts/evaluate_local.py
Outputs modes, citations and latency only; no credentials or customer identifiers.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bankmore_intelligence.config import Settings
from bankmore_intelligence.db import database, migrate
from bankmore_intelligence.demo import seed
from bankmore_intelligence.rag import Ollama, seed_documents
from bankmore_intelligence.service import Investigation


def main():
    with tempfile.TemporaryDirectory(prefix='bankmore-eval-') as directory:
        settings = Settings(database_url=f'sqlite:///{directory}/evaluation.db', mode='ollama',
            pseudonym_key='synthetic-evaluation-key-not-production',
            chat_model=os.getenv('OLLAMA_CHAT_MODEL', 'qwen3:4b'),
            embed_model=os.getenv('OLLAMA_EMBED_MODEL', 'embeddinggemma'))
        engine = database(settings.database_url)
        try:
            migrate(engine)
            seed_documents(engine, settings, Ollama(settings))
            service = Investigation(engine, settings)
            ids = seed(service)
            results = []
            for name, case_id in ids.items():
                report = service.draft(case_id, 1, {'subject': 'evaluation', 'queue': 'operacoes'})['content']
                result = {'scenario': name, 'generation': report['generation'], 'retrieval': report['retrieval']['mode'],
                    'recommendation': report['proposal']['recomendacao'], 'latency_ms': report['latency_ms'],
                    'hypotheses': report['proposal']['hipoteses'], 'procedures': report['proposal']['procedimentos']}
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            if any(r['generation']['mode'] != 'ollama' or r['retrieval'] != 'hybrid-rrf' for r in results):
                raise SystemExit('Falhou: pelo menos um cenário usou fallback')
            expected = {'suspeita': 'INVESTIGAR', 'contexto': 'REVISAR_CONTEXTO', 'inconclusivo': 'COLETAR_EVIDENCIAS'}
            if any(r['recommendation'] != expected[r['scenario']] for r in results):
                raise SystemExit('Falhou: recomendação de triagem diferente do esperado nos fixtures')
        finally:
            engine.dispose()


if __name__ == '__main__':
    main()
