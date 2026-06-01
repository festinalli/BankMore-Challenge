"""
BankMore Fraud Detector — Sprint 2

Implementação Python da MESMA topologia que o job PyFlink teria:
    transferencia.solicitada  →  [decisor com state por CPF]  →  3 sinks Kafka
                                                                   ├─ transferencia.aprovada
                                                                   ├─ transferencia.rejeitada
                                                                   └─ fraude.alerta  (cópia de aprovadas com valor alto)

Por que Python puro e não PyFlink real agora:
    O wheel do apache-flink (~350MB) consistentemente expira no PyPI a partir
    daqui. Sprint 4 substitui por PyFlink real submetido ao JM/TM externo
    (e aí ganhamos exactly-once, checkpoint distribuído e horizontal scale).
    A lógica de decisão, o formato dos eventos e os 3 tópicos são idênticos ao
    que o job Flink seria — o swap é local, sem mexer em backend nem schema.

Regras (Sprint 2, sem ML):
    R1  cpfOrigem == cpfDestino                       → REJEITADA (AUTO_TRANSFERENCIA)
    R2  valor <= 0                                    → REJEITADA (VALOR_INVALIDO)
    R3  ≥ BURST_LIMITE em JANELA_BURST_SEGUNDOS por CPF → REJEITADA (BURST_*)
    R4  valor >= VALOR_ALTO_BRL                       → APROVADA + cópia em fraude.alerta
    R5  default                                       → APROVADA

State: dict cpf → deque[(timestamp_ms, id)], com pruning por TTL.
Limite ao escalar: state em memória local = single-instance. Pra scale-out,
ou (a) PyFlink real com KeyedState, ou (b) Redis como state externo.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Tuple

from confluent_kafka import Consumer, KafkaError, Producer

# --------------------------------------------------------------------------------------
# Config (env override)
# --------------------------------------------------------------------------------------
KAFKA_BROKERS  = os.getenv("KAFKA_BROKERS",  "kafka:29092")
SOURCE_TOPIC   = os.getenv("SOURCE_TOPIC",   "transferencia.solicitada")
SINK_APROVADA  = os.getenv("SINK_APROVADA",  "transferencia.aprovada")
SINK_REJEITADA = os.getenv("SINK_REJEITADA", "transferencia.rejeitada")
SINK_ALERTA    = os.getenv("SINK_ALERTA",    "fraude.alerta")
GROUP_ID       = os.getenv("GROUP_ID",       "fraud-detector")

VALOR_ALTO_BRL          = float(os.getenv("VALOR_ALTO_BRL",          "10000.00"))
BURST_LIMITE            = int  (os.getenv("BURST_LIMITE_POR_MINUTO", "4"))
JANELA_BURST_SEGUNDOS   = int  (os.getenv("JANELA_BURST_SEGUNDOS",   "60"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fraud-detector")


# --------------------------------------------------------------------------------------
# State por CPF — equivalente ao KeyedState do Flink
# --------------------------------------------------------------------------------------
class BurstState:
    """Janela rolling de transações por CPF, em memória."""

    def __init__(self, janela_segundos: int):
        self._janela_ms = janela_segundos * 1000
        self._por_cpf: Dict[str, Deque[Tuple[int, str]]] = defaultdict(deque)

    def registrar_e_contar(self, cpf: str, ts_ms: int, tid: str) -> int:
        """Adiciona a transação, expira antigas, retorna contagem atual na janela."""
        if not cpf:
            return 0
        d = self._por_cpf[cpf]
        cutoff = ts_ms - self._janela_ms
        while d and d[0][0] < cutoff:
            d.popleft()
        d.append((ts_ms, tid))
        return len(d)

    def contar_atual(self, cpf: str, ts_ms: int) -> int:
        """Conta sem registrar — usado quando vamos rejeitar."""
        d = self._por_cpf.get(cpf)
        if not d:
            return 0
        cutoff = ts_ms - self._janela_ms
        while d and d[0][0] < cutoff:
            d.popleft()
        return len(d)


# --------------------------------------------------------------------------------------
# Decisor
# --------------------------------------------------------------------------------------
class FraudDecider:
    MODELO = "rules-v1"

    # Campos esperados no evento — tolerante a PascalCase do .NET / camelCase do front
    _ALIASES = {
        "id":            ("id", "Id"),
        "correlationId": ("correlationId", "CorrelationId"),
        "cpfOrigem":     ("cpfOrigem", "CpfOrigem"),
        "cpfDestino":    ("cpfDestino", "CpfDestino"),
        "valor":         ("valor", "Valor"),
        "tipo":          ("tipo", "Tipo"),
        "taxa":          ("taxa", "Taxa"),
        "timestamp":     ("timestamp", "Timestamp", "timestampMs"),
        "canal":         ("canal", "Canal"),
    }

    def __init__(self):
        self._state = BurstState(JANELA_BURST_SEGUNDOS)

    def decidir(self, evt: dict) -> Tuple[str, List[str], dict]:
        """Normaliza para camelCase canônico e decide."""
        norm = self._normalizar(evt)
        cpf_o = (norm.get("cpfOrigem")  or "").strip()
        cpf_d = (norm.get("cpfDestino") or "").strip()
        valor = float(norm.get("valor") or 0)
        ts_ms = self._timestamp(norm)
        tid   = norm.get("id") or ""

        motivos: List[str] = []

        if cpf_o and cpf_o == cpf_d:
            motivos.append("AUTO_TRANSFERENCIA")
            return "REJEITADA", motivos, self._enriquecer(norm, ts_ms)

        if valor <= 0:
            motivos.append("VALOR_INVALIDO")
            return "REJEITADA", motivos, self._enriquecer(norm, ts_ms)

        # Burst — N+1 dentro da janela ⇒ rejeita
        atual = self._state.contar_atual(cpf_o, ts_ms)
        if atual + 1 >= BURST_LIMITE:
            motivos.append(f"BURST_{atual + 1}_EM_{JANELA_BURST_SEGUNDOS}s")
            return "REJEITADA", motivos, self._enriquecer(norm, ts_ms)

        # Passou nas regras duras — registra no state e aprova
        self._state.registrar_e_contar(cpf_o, ts_ms, tid)
        return "APROVADA", motivos, self._enriquecer(norm, ts_ms)

    @classmethod
    def _normalizar(cls, evt: dict) -> dict:
        out: dict = {}
        for canon, keys in cls._ALIASES.items():
            for k in keys:
                if k in evt and evt[k] is not None:
                    out[canon] = evt[k]
                    break
        return out

    def _enriquecer(self, evt: dict, ts_ms: int) -> dict:
        agora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return {
            **evt,
            "decididoEm": agora_ms,
            "latenciaMs": max(agora_ms - ts_ms, 0),
            "modeloVersao": self.MODELO,
        }

    @staticmethod
    def _timestamp(evt: dict) -> int:
        v = evt.get("timestamp")
        if isinstance(v, (int, float)) and v > 0:
            return int(v if v > 1e12 else v * 1000)
        if isinstance(v, str) and v:
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except ValueError:
                pass
        return int(datetime.now(timezone.utc).timestamp() * 1000)


# --------------------------------------------------------------------------------------
# Wiring Kafka
# --------------------------------------------------------------------------------------
def _delivery(err, msg):
    if err is not None:
        log.error("Falha entrega: %s (topic=%s)", err, msg.topic() if msg else "?")


def main() -> int:
    log.info(
        "fraud-detector iniciando | brokers=%s source=%s burst=%d/%ds valor_alto=%.2f",
        KAFKA_BROKERS, SOURCE_TOPIC, BURST_LIMITE, JANELA_BURST_SEGUNDOS, VALOR_ALTO_BRL,
    )

    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([SOURCE_TOPIC])

    producer = Producer({
        "bootstrap.servers": KAFKA_BROKERS,
        "acks": "all",
        "enable.idempotence": True,
        "max.in.flight.requests.per.connection": 5,
        "linger.ms": 10,
    })

    decider = FraudDecider()
    running = True

    def stop(_sig, _frm):
        nonlocal running
        log.info("SIGTERM/SIGINT — encerrando")
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    counts = {"APROVADA": 0, "REJEITADA": 0, "ALERTA": 0}

    try:
        while running:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("Erro Kafka: %s", msg.error())
                continue

            raw = msg.value().decode("utf-8")
            try:
                evt = json.loads(raw)
            except json.JSONDecodeError as e:
                log.error("JSON inválido descartado: %s | raw=%s", e, raw[:200])
                continue

            decisao, motivos, out = decider.decidir(evt)
            out["decisao"] = decisao
            if motivos:
                out["motivos"] = motivos

            key = (out.get("cpfOrigem") or out.get("CpfOrigem") or "").encode()
            payload = json.dumps(out, ensure_ascii=False).encode("utf-8")

            if decisao == "APROVADA":
                producer.produce(SINK_APROVADA, value=payload, key=key, callback=_delivery)
                counts["APROVADA"] += 1
                log.info(
                    "APROVADA id=%s cpf=%s*** valor=%s",
                    out.get("id"), (out.get("cpfOrigem") or "")[:3], out.get("valor"),
                )

                if float(out.get("valor") or 0) >= VALOR_ALTO_BRL:
                    producer.produce(SINK_ALERTA, value=payload, key=key, callback=_delivery)
                    counts["ALERTA"] += 1
                    log.warning(
                        "ALERTA id=%s cpf=%s*** valor=%s (>= %.2f)",
                        out.get("id"), (out.get("cpfOrigem") or "")[:3], out.get("valor"), VALOR_ALTO_BRL,
                    )
            else:  # REJEITADA
                producer.produce(SINK_REJEITADA, value=payload, key=key, callback=_delivery)
                counts["REJEITADA"] += 1
                log.warning(
                    "REJEITADA id=%s cpf=%s*** valor=%s motivos=%s",
                    out.get("id"), (out.get("cpfOrigem") or "")[:3], out.get("valor"), motivos,
                )

            producer.poll(0)

        producer.flush(10)
    finally:
        consumer.close()
        log.info("counts=%s", counts)

    return 0


if __name__ == "__main__":
    sys.exit(main())
