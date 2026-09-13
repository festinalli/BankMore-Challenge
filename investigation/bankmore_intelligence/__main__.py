import argparse
import json
import secrets
from pathlib import Path

from dotenv import load_dotenv

from .config import Settings
from .db import database, migrate
from .demo import seed
from .rag import Ollama, seed_documents
from .service import Investigation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["setup-demo", "migrate", "seed-demo", "index-knowledge", "serve"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5010)
    args = parser.parse_args()
    env_path = Path(__file__).resolve().parents[1] / ".env.local"
    if args.command == "setup-demo":
        if env_path.exists():
            print("Configuração existente preservada: " + str(env_path))
            return
        agent, human = secrets.token_hex(24), secrets.token_hex(24)
        identities = {
            agent: {"subject": "assistente-demo", "queue": "operacoes", "scopes": ["read", "draft"]},
            human: {"subject": "analista-demo", "queue": "operacoes", "scopes": ["read", "draft", "review"]}}
        env_path.write_text("\n".join([
            "INTELLIGENCE_MODE=demo", "INTELLIGENCE_DATABASE_URL=sqlite:///intelligence.db",
            "INTELLIGENCE_PSEUDONYM_KEY=" + secrets.token_hex(32),
            "INTELLIGENCE_DB_PASSWORD=" + secrets.token_hex(24),
            "INTELLIGENCE_IDENTITIES=" + json.dumps(identities),
            "INTELLIGENCE_MCP_TOKEN=" + agent,
            "INTELLIGENCE_REVIEW_TOKEN=" + human,
            "OLLAMA_CHAT_MODEL=qwen3:4b", "OLLAMA_EMBED_MODEL=embeddinggemma", ""]), encoding="utf-8")
        print("Configuração local criada: " + str(env_path))
        return
    load_dotenv(env_path)
    settings = Settings()
    settings.validate()
    engine = database(settings.database_url)
    migrate(engine)
    if args.command == "seed-demo":
        if settings.mode != "demo":
            raise ValueError("Seed sintético exige INTELLIGENCE_MODE=demo")
        seed_documents(engine, settings)
        print(json.dumps(seed(Investigation(engine, settings))))
    elif args.command == "index-knowledge":
        seed_documents(engine, settings, Ollama(settings) if settings.mode == "ollama" else None)
    elif args.command == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings, engine), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
