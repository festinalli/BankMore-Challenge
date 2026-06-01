# Infra — Docker Compose

`docker-compose.yml` será escrito do zero no Sprint 1 (14/05/2026).

## Serviços previstos

| Serviço | Imagem | Porta | Healthcheck |
|---|---|---|---|
| postgres | postgres:16-alpine | 5432 | `pg_isready` |
| redis | redis:7-alpine | 6379 | `redis-cli ping` |
| zookeeper | confluentinc/cp-zookeeper:7.5.0 | 2181 | `nc localhost 2181` |
| kafka | confluentinc/cp-kafka:7.5.0 | 9092, 29092 | `kafka-broker-api-versions` |
| schema-registry | confluentinc/cp-schema-registry:7.5.0 | 8081 | `curl /subjects` |
| kafka-ui | provectuslabs/kafka-ui:latest | 8080 | — |
| flink-jobmanager | flink:1.18-java11 | 8082 | `curl /v1/overview` |
| flink-taskmanager | flink:1.18-java11 | — | — |
| ml-service | local build | 5003 | `curl /health` |
| fraud-detector | local build (PyFlink job submitter) | — | — |
| contacorrente-api | local build (.NET) | 5000 | `curl /health` |
| transferencia-api | local build (.NET) | 5001 | `curl /health` |
| tarifas-worker | local build (.NET) | — | — |
| prometheus | prom/prometheus:latest | 9090 | — |
| grafana | grafana/grafana:latest | 3000 | — |
| jaeger | jaegertracing/all-in-one:latest | 16686 | — |

## Cuidados

- **Um único bloco `services:`** (não duplicar como no BankFest_Fink).
- Conflito de porta: ML em **5003**, NÃO 5000 (5000 é a API ContaCorrente).
- `depends_on` com `condition: service_healthy` para não subir o que precisa do banco antes do banco estar pronto.
- Volumes nomeados para `postgres_data`, `redis_data`, `kafka_data`, `flink_checkpoints`.
- Network única `bankmore_network`.
