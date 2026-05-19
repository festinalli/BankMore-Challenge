# 0011 — Flink PrometheusReporter nativo (Sprint 5.A)

**Status:** Aceito · **Data:** 2026-05-19

## Contexto

Sprint 4.E instrumentou .NET (APIs + Worker) e Python (ML) com Prometheus,
mas o **fraud-detector** ficou sem `/metrics`. A tentativa de usar
`prometheus_client` no `fraud_detector_job.py` falhou com
`TypeError: cannot pickle '_thread.lock' object` porque o Flink usa
`cloudpickle` pra serializar o operator entre slots e os
`Counter/Histogram` do `prometheus_client` carregam `threading.Lock` interno.

Soluções avaliadas:

1. **Inicializar métricas lazy no `open()` do operator** — não resolve.
   O operator roda no Python SDK Worker do Beam (processo separado do main),
   então o `/metrics` ficaria isolado lá e o Prometheus não acharia.
2. **Pushgateway intermediário** — adiciona componente, complica retries.
3. **Flink PrometheusReporter nativo (JM/TM)** — JAR já embutido em
   `/opt/flink/plugins/metrics-prometheus/flink-metrics-prometheus-1.18.1.jar`,
   expõe centenas de métricas auto-instrumentadas (operators, sinks,
   checkpoints, Kafka source/sink lag, JVM).

## Decisão

Usar o **PrometheusReporter nativo** do Flink, configurado via
`Configuration()` no `main()` do job (não via `flink-conf.yaml`, que o
PyFlink local-mode ignora).

Pegada: o reporter expõe na porta `9249` (range `9249-9260` pra evitar
conflito). Compose expõe a porta. `prometheus.yml` raspa
`fraud-detector:9249` com `metrics_path: /`.

Detalhe não-óbvio: **PyFlink local-mode não carrega `plugins/`
automaticamente** (classloader isolado é desabilitado quando o cluster é
embarcado). O Dockerfile copia o JAR de `plugins/` para `lib/` (ambos:
`/opt/flink/lib/` e `$PYFLINK_HOME/lib/`) pra que entre no classpath direto.

## Consequências

- ✅ Métricas RICAS do Flink no Prometheus: `flink_jobmanager_numRunningJobs`,
  `flink_taskmanager_job_task_operator_KafkaProducer_record_send_rate`,
  `flink_jobmanager_job_lastCheckpointDuration`, etc.
- ✅ Sem custo de instrumentação manual no código Python.
- ✅ Fecha o gap deixado pelo Sprint 4.E.
- ⚠ Alta cardinalidade nos labels (operator_name, task_attempt_id) — se
  virar problema, configurar `metrics.reporter.prom.filter.includes`.
- ⚠ Hack do copy JAR pra `lib/` é específico do local-mode. Quando migrar
  pra cluster distribuído (Sprint 7+), volta a estratégia padrão de
  `plugins/`.
