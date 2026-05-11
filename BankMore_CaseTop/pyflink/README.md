# PyFlink Fraud Detection Job

Implementação a partir do Sprint 2 (14/05/2026).

## Princípios

- **Event-time + watermarks** — não usar ProcessingTime (resultados não-determinísticos no replay).
- **State na JVM** — `MapState`/`ValueState` em RocksDB. Redis é só feature store quente para o ML, não para janela.
- **Async I/O** para chamar ML — nunca `requests.post` síncrono dentro de operador (bloqueia slot).
- **Side outputs** em vez de tópicos separados no `add_sink` — melhor controle de paralelismo.
- **Checkpoint a cada 60s**, exactly-once, RocksDB backend, savepoints em volume.

## Decisões abertas para a quinta

- Modelo embedado (`joblib.load` no operador) **vs** chamada HTTP ao Flask.
  Tradeoff: embedado = latência sub-ms mas reload exige restart; HTTP = versionamento dinâmico mas custo de rede.
  Decisão preliminar: **HTTP via Async I/O** no Sprint 2-3 para manter baixa fricção; avaliar embedado se p95 > 500ms.

- Janela tumbling (60s) **vs** sliding (60s, slide 10s) **vs** session (gap 5min).
  Decisão preliminar: **sliding 60s/10s** — fraude por burst se beneficia de overlap.
