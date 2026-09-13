from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AlertEvent(BaseModel):
    """Only detector output fields are accepted; customer text never enters the prompt."""
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    cpfOrigem: str = Field(pattern=r"^\d{11}$")
    valor: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    tipo: Literal["PIX", "TED", "TEF"]
    timestamp: datetime
    decididoEm: datetime
    decisao: Literal["APROVADA", "REJEITADA"]
    motivos: list[str] = Field(default_factory=list, max_length=20)
    modeloVersao: str = Field(default="nao-informado", max_length=100, pattern=r"^[\w.+-]+$")
    scoreFraude: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def chronology(self):
        if self.timestamp > self.decididoEm:
            raise ValueError("Evento posterior à própria decisão")
        return self

    @field_validator("timestamp", "decididoEm")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamp deve conter timezone")
        return value

    @field_validator("motivos")
    @classmethod
    def reasons(cls, values):
        import re
        if any(not re.fullmatch(r"[A-Z0-9_.-]{1,100}[sS]?", value) for value in values):
            raise ValueError("Motivo deve ser código do detector, não texto livre")
        return values


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: str = Field(min_length=1, max_length=1000)
    evidencias: list[str] = Field(min_length=1, max_length=10)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hipoteses: list[Hypothesis] = Field(min_length=1, max_length=4)
    recomendacao: Literal["INVESTIGAR", "REVISAR_CONTEXTO", "COLETAR_EVIDENCIAS"]
    limitacoes: list[str] = Field(min_length=1, max_length=8)
    procedimentos: list[str] = Field(max_length=5)

    @field_validator("limitacoes")
    @classmethod
    def bounded_limitations(cls, values):
        if any(not value or len(value) > 500 for value in values):
            raise ValueError("Limitação deve ter 1 a 500 caracteres")
        return values


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str = Field(max_length=64)
    expected_version: int = Field(ge=1)
    outcome: Literal["FRAUDE_CONFIRMADA", "FALSO_POSITIVO", "INCONCLUSIVO"]
    rationale: str = Field(min_length=10, max_length=1500)

    @field_validator("rationale")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 10:
            raise ValueError("Justificativa deve ter pelo menos 10 caracteres úteis")
        return value.strip()


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
