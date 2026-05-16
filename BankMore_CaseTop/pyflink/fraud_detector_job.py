"""
BankMore Fraud Detector — Sprint 2
Job PyFlink que decide aprovar/rejeitar transferências em tempo real.

Pipeline:
    transferencia.solicitada  (JSON)
        │
        ▼
    Parser (JSON → dict + extrai event-time)
        │
        ▼
    WatermarkStrategy (event-time, 5s out-of-orderness)
        │
        ▼
    keyBy(cpfOrigem) → KeyedProcessFunction(FraudDecider)
        │  • MapState<timestamp, boolean> com TTL de 60s (janela rolling de burst)
        │  • Regras determinísticas (Sprint 2). ML real entra no Sprint 3.
        │
        ├──▶ side-output APROVADA    → transferencia.aprovada
        ├──▶ side-output REJEITADA   → transferencia.rejeitada
        └──▶ side-output ALERTA      → fraude.alerta

Por que assim:
    - Event-time + watermark: replays determinísticos, fora-de-ordem tratado
    - MapState (não Redis): estado local na JVM, escalado pelo Flink
    - State TTL: limpeza automática, evita memory leak
    - Side outputs: 1 operator, 3 destinos, sem re-particionar
    - Checkpointing exactly-once: configurado via compose (RocksDB, 60s)

Roda local-mode dentro do próprio container (não submete ao JM/TM).
Sprint 4 muda para submissão no cluster (e abre o caminho pra scale-out).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

from pyflink.common import Configuration, Duration, Time, Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import (
    CheckpointingMode,
    OutputTag,
    ProcessFunction,
    RuntimeContext,
    StreamExecutionEnvironment,
)
from pyflink.datastream.connectors.kafka import (
    KafkaOffsetsInitializer,
    KafkaRecordSerializationSchema,
    KafkaSink,
    KafkaSource,
)
from pyflink.datastream.functions import KeyedProcessFunction
from pyflink.datastream.state import MapStateDescriptor, StateTtlConfig

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
BURST_LIMITE_POR_MINUTO = int  (os.getenv("BURST_LIMITE_POR_MINUTO", "4"))
JANELA_BURST_SEGUNDOS   = int  (os.getenv("JANELA_BURST_SEGUNDOS",   "60"))
WATERMARK_DELAY_SECONDS = int  (os.getenv("WATERMARK_DELAY_SECONDS", "5"))
CHECKPOINT_INTERVAL_MS  = int  (os.getenv("CHECKPOINT_INTERVAL_MS",  "60000"))

# Side outputs (não viram tópicos diretamente — cada um vai pra um sink Kafka próprio)
TAG_APROVADA  = OutputTag("aprovada",  Types.STRING())
TAG_REJEITADA = OutputTag("rejeitada", Types.STRING())
TAG_ALERTA    = OutputTag("alerta",    Types.STRING())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fraud-detector")


# --------------------------------------------------------------------------------------
# Timestamp extraction
# --------------------------------------------------------------------------------------
class TransferenciaTimestampAssigner(TimestampAssigner):
    """Extrai event-time do campo `timestamp` (epoch millis) ou `timestampMs`."""

    def extract_timestamp(self, value: str, record_timestamp: int) -> int:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return record_timestamp

        if isinstance(payload.get("timestampMs"), int):
            return int(payload["timestampMs"])
        if isinstance(payload.get("timestamp"), (int, float)):
            ts = payload["timestamp"]
            return int(ts if ts > 1e12 else ts * 1000)
        if isinstance(payload.get("timestamp"), str):
            try:
                dt = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except ValueError:
                pass
        return record_timestamp


# --------------------------------------------------------------------------------------
# FraudDecider — coração do job
# --------------------------------------------------------------------------------------
class FraudDecider(KeyedProcessFunction):
    """
    Decide APROVADA / REJEITADA / ALERTA para cada transferência.

    State: MapState<long timestampMs, byte 1> — uma chave por solicitação no minuto.
    TTL = janela de burst (default 60s). Limpeza automática pelo Flink.
    """

    BURST_STATE_NAME = "burst-window"

    def open(self, ctx: RuntimeContext):
        ttl = StateTtlConfig.new_builder(Time.seconds(JANELA_BURST_SEGUNDOS * 2)) \
            .set_update_type(StateTtlConfig.UpdateType.OnCreateAndWrite) \
            .set_state_visibility(StateTtlConfig.StateVisibility.NeverReturnExpired) \
            .cleanup_in_rocksdb_compact_filter(1000) \
            .build()

        descriptor = MapStateDescriptor(self.BURST_STATE_NAME, Types.LONG(), Types.BYTE())
        descriptor.enable_time_to_live(ttl)
        self._burst = ctx.get_map_state(descriptor)

    def process_element(self, value: str, ctx: "KeyedProcessFunction.Context"):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as e:
            log.error("JSON inválido descartado: %s | raw=%s", e, value[:200])
            return

        event_ts = ctx.timestamp() or int(datetime.now(timezone.utc).timestamp() * 1000)
        cpf_origem  = payload.get("cpfOrigem")  or payload.get("CpfOrigem")  or ""
        cpf_destino = payload.get("cpfDestino") or payload.get("CpfDestino") or ""
        valor       = float(payload.get("valor") or payload.get("Valor") or 0)
        tipo        = payload.get("tipo")       or payload.get("Tipo")     or "PIX"

        decisao, motivos = self._decidir(cpf_origem, cpf_destino, valor, event_ts)
        decided_at = int(datetime.now(timezone.utc).timestamp() * 1000)

        out = {
            **payload,
            "decisao": decisao,
            "motivos": motivos,
            "decididoEm": decided_at,
            "latenciaMs": max(decided_at - event_ts, 0),
            "modeloVersao": "rules-v1",
        }
        out_json = json.dumps(out, ensure_ascii=False)

        if decisao == "APROVADA":
            ctx.output(TAG_APROVADA, out_json)
            log.info("APROVADA id=%s cpf=%s*** valor=%.2f tipo=%s",
                     payload.get("id"), cpf_origem[:3], valor, tipo)
        elif decisao == "REJEITADA":
            ctx.output(TAG_REJEITADA, out_json)
            log.warning("REJEITADA id=%s cpf=%s*** valor=%.2f motivos=%s",
                        payload.get("id"), cpf_origem[:3], valor, motivos)

        # ALERTA é sempre cópia (não bloqueia a aprovação) quando valor alto e aprovada
        if decisao == "APROVADA" and valor >= VALOR_ALTO_BRL:
            ctx.output(TAG_ALERTA, out_json)
            log.warning("ALERTA id=%s cpf=%s*** valor=%.2f (>= R$ %.2f)",
                        payload.get("id"), cpf_origem[:3], valor, VALOR_ALTO_BRL)

    def _decidir(self, cpf_origem: str, cpf_destino: str, valor: float, event_ts: int):
        motivos: list[str] = []

        # Regra 1: autotransferência
        if cpf_origem and cpf_origem == cpf_destino:
            motivos.append("AUTO_TRANSFERENCIA")
            return "REJEITADA", motivos

        # Regra 2: valor inválido
        if valor <= 0:
            motivos.append("VALOR_INVALIDO")
            return "REJEITADA", motivos

        # Regra 3: burst — janela rolling de N segundos
        cutoff = event_ts - (JANELA_BURST_SEGUNDOS * 1000)
        # remove entries antigas e conta atuais
        ativos = 0
        to_drop: list[int] = []
        for ts_existing in self._burst.keys():
            if ts_existing < cutoff:
                to_drop.append(ts_existing)
            else:
                ativos += 1
        for ts_old in to_drop:
            self._burst.remove(ts_old)

        # Inclui a transação atual no count
        if ativos + 1 >= BURST_LIMITE_POR_MINUTO:
            motivos.append(f"BURST_{ativos + 1}_EM_{JANELA_BURST_SEGUNDOS}s")
            # NÃO grava no state — rejeitada não conta pra próximas
            return "REJEITADA", motivos

        # Registra essa transação no state (passou nas regras duras)
        self._burst.put(event_ts, 1)
        return "APROVADA", motivos


# --------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------
def build_pipeline(env: StreamExecutionEnvironment) -> None:
    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(KAFKA_BROKERS)
        .set_topics(SOURCE_TOPIC)
        .set_group_id(GROUP_ID)
        .set_starting_offsets(KafkaOffsetsInitializer.earliest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    watermark = (
        WatermarkStrategy
        .for_bounded_out_of_orderness(Duration.of_seconds(WATERMARK_DELAY_SECONDS))
        .with_timestamp_assigner(TransferenciaTimestampAssigner())
    )

    stream = env.from_source(source, watermark, "kafka-source")

    # Key by cpfOrigem — onde o state vive
    keyed = stream.key_by(
        lambda v: (json.loads(v).get("cpfOrigem") or json.loads(v).get("CpfOrigem") or ""),
        key_type=Types.STRING(),
    )

    main = keyed.process(FraudDecider(), output_type=Types.STRING())

    # Side outputs viram sinks Kafka separados
    _sink(main.get_side_output(TAG_APROVADA),  SINK_APROVADA,  "sink-aprovada")
    _sink(main.get_side_output(TAG_REJEITADA), SINK_REJEITADA, "sink-rejeitada")
    _sink(main.get_side_output(TAG_ALERTA),    SINK_ALERTA,    "sink-alerta")


def _sink(stream, topic: str, name: str) -> None:
    sink = (
        KafkaSink.builder()
        .set_bootstrap_servers(KAFKA_BROKERS)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic(topic)
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
        .build()
    )
    stream.sink_to(sink).name(name).uid(name)


def main() -> int:
    log.info("Iniciando fraud-detector | brokers=%s source=%s", KAFKA_BROKERS, SOURCE_TOPIC)

    config = Configuration()
    config.set_string("execution.checkpointing.mode", "EXACTLY_ONCE")
    config.set_string("execution.checkpointing.interval", f"{CHECKPOINT_INTERVAL_MS} ms")
    config.set_string("execution.checkpointing.min-pause", "30000 ms")
    config.set_string("execution.checkpointing.timeout", "10 min")
    config.set_string("state.backend.type", "rocksdb")

    env = StreamExecutionEnvironment.get_execution_environment(config)
    env.set_parallelism(1)  # Sprint 2 single-slot; aumenta no Sprint 4

    build_pipeline(env)

    env.execute("bankmore-fraud-detector")
    return 0


if __name__ == "__main__":
    sys.exit(main())
