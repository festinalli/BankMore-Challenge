# PyFlink Fraud Detector

Detector de fraude em transferências bancárias em tempo real.

## Implementação atual: PyFlink 1.18 (Sprint 2.5)

`fraud_detector_job.py` — job com:
- `KafkaSource` reading `transferencia.solicitada`
- `WatermarkStrategy.for_bounded_out_of_orderness(5s)` + event-time
- `key_by(cpfOrigem)` particionando por chave de domínio
- `KeyedProcessFunction` com `MapState<long, byte>` + TTL = janela de burst
- Side outputs (`OutputTag`) para 3 destinos: aprovada, rejeitada, alerta
- `state.backend=rocksdb`, `checkpoint=EXACTLY_ONCE`, intervalo 60s

Imagem: `Dockerfile.flink` (multi-stage com base `flink:1.18-scala_2.12-java11`).

### Por que tem o `Dockerfile` simples também

`Dockerfile` (sem o `.flink`) builda um detector Python puro com a **mesma lógica**
(`fraud_detector.py`). Foi a versão usada no Sprint 2 enquanto resolvia o gargalo de rede
do PyFlink. Continua versionado pra:
- Comparar comportamento entre os dois
- Fallback rápido se algo der errado no PyFlink
- Testes locais que não precisam de Flink

## Como buildar a imagem PyFlink

```bash
# 1) Baixa o tarball de 220MB do apache-flink-libraries no host
#    (curl com resume — daemon Docker dá timeout no PyPI)
bash pyflink/fetch_pyflink_libs.sh

# 2) Build normal — o Dockerfile faz COPY do tarball local
docker compose --env-file .env -f infra/compose/docker-compose.yml build fraud-detector
```

## Diagnóstico que salvou o sprint

| Sintoma | Causa real | Solução |
|---|---|---|
| `pip install apache-flink` timeout | apache-flink em si é 6MB, mas dep `apache-flink-libraries` é **220MB sdist** que o daemon Docker não consegue puxar | Download no host (curl, ~6s @ 32MB/s) + `COPY` no Dockerfile |
| `pemja` falha com "Include folder should be at /opt/java/openjdk/include but doesn't exist" | Imagem `flink:1.18` tem só JRE, `pemja==0.3.0` precisa do **JDK** pra compilar (sem wheel pra Linux) | `apt-get install openjdk-11-jdk-headless` + linkar `jni.h` em `/opt/java/openjdk/include` |
| `key_by` chamava `json.loads(v)` 2× por record | Lambda mal escrito | Extrator dedicado com try/except |

## Princípios

- **Event-time + watermarks** — sem `ProcessingTime` (resultados não-determinísticos no replay)
- **State na JVM (RocksDB)** — `MapState`/`ValueState`, Redis é só feature store quente pro ML
- **Side outputs** em vez de tópicos múltiplos no sink — controle de paralelismo
- **Checkpoint EXACTLY_ONCE** a cada 60s
- Mesmos tópicos e formato de evento que o detector Python — swap reversível

## Decisões pendentes para Sprint 3+

- Modelo embedado (`joblib.load` no operador) **vs** chamada HTTP ao Flask
  - Tradeoff: embedado = latência sub-ms mas reload exige restart; HTTP = versionamento dinâmico mas custo de rede
  - Preliminar: HTTP via Async I/O; avaliar embedado se p95 > 500ms
- Janela tumbling (60s) **vs** sliding (60s, slide 10s) **vs** session (gap 5min)
  - Preliminar: sliding 60s/10s — fraude por burst se beneficia de overlap
- Submissão ao cluster (JM/TM externo via `flink run -py`) **vs** local-mode dentro do container
