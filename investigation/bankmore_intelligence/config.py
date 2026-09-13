import json
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("INTELLIGENCE_DATABASE_URL", "sqlite:///intelligence.db"))
    identities: dict = field(default_factory=lambda: json.loads(os.getenv("INTELLIGENCE_IDENTITIES", "{}")))
    pseudonym_key: str = field(default_factory=lambda: os.getenv("INTELLIGENCE_PSEUDONYM_KEY", ""))
    mode: str = field(default_factory=lambda: os.getenv("INTELLIGENCE_MODE", "demo"))
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    chat_model: str = field(default_factory=lambda: os.getenv("OLLAMA_CHAT_MODEL", "qwen3:4b"))
    embed_model: str = field(default_factory=lambda: os.getenv("OLLAMA_EMBED_MODEL", "embeddinggemma"))
    origins: list[str] = field(default_factory=lambda: os.getenv("INTELLIGENCE_ORIGINS", "http://localhost:4200").split(","))

    def validate(self):
        if self.mode not in {"demo", "ollama"}:
            raise ValueError("INTELLIGENCE_MODE deve ser demo ou ollama")
        if len(self.pseudonym_key) < 32 or not self.identities:
            raise ValueError("Configure identidades e chave de pseudonimização com pelo menos 32 caracteres")
        for token, identity in self.identities.items():
            if len(token) < 32 or not identity.get("subject") or not identity.get("queue"):
                raise ValueError("Identidade inválida: token >=32, subject e queue obrigatórios")
            if not set(identity.get("scopes", [])) <= {"read", "draft", "review"}:
                raise ValueError("Escopo desconhecido")
