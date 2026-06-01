# Storyline para entrevista

Versão expandida do pitch de 4 minutos. Use como roteiro mental, não decore.

## Hook (30s)

> "Construí um sistema bancário onde toda transferência passa por um pipeline de detecção de fraude em tempo real **antes** de ser efetivada. PyFlink decide em sub-segundo, ML treinado em dataset sintético, observabilidade ponta-a-ponta. Quero te mostrar como ele bloqueia um ataque ao vivo."

## Por que assim (1 min)

- Banco moderno **não pode** bloquear apenas com regras simples — fraudadores fracionam, fazem burst, usam contas-mula.
- Resposta síncrona em < 1s **e** processamento stateful em 1h de janela são requisitos contraditórios para uma API tradicional.
- Solução: **separar solicitação de efetivação**. API responde 202 com `correlationId`; PyFlink decide; cliente recebe push.

## Decisões arquiteturais (2 min)

### 1. Event-driven com Kafka como espinha dorsal
- Tópicos: `transferencia.solicitada` → `transferencia.{aprovada,rejeitada,alerta}`
- Avro + Schema Registry → contratos versionados, evita drift entre produtores
- **Tradeoff:** complexidade de UX (cliente espera push) por escalabilidade horizontal

### 2. PyFlink no path crítico, não como afterthought
- Event-time com watermark de 5s — replay determinístico
- `KeyedState` com RocksDB — janela de 1h por CPF sem custo de Redis
- Exactly-once com checkpoint a cada 60s
- Side outputs em vez de tópicos múltiplos no sink
- **Tradeoff:** ops complexity (precisa savepoint para deploy) por correctness

### 3. ML híbrido — regras + modelo
- Regras DURAS no Flink: autotransferência, valor inválido, burst (≥4 tx/60s).
  Determinísticas, baratas, compliance.
- Modelo XGBoost no Flask: 7 features, score [0,1], threshold 0.95 calibrado pra
  recall ≥ 0.85 no eval. ROC-AUC 0.999 em dataset sintético (~100k amostras, 2% fraude).
- Ordem: regras duras primeiro (fail fast), modelo só pra quem passa.
- **Fail-open:** se /predict cair ou demorar > 2s, segue só com regras (não derruba
  transferências legítimas se ML estiver indisponível).
- **Versionamento:** todo evento decididoEm carrega `modeloVersao` (ex.: `rules-v1+xgboost-v1`).
  Permite A/B online no Sprint 4 (shadow mode com 2 modelos lado a lado).
- **Tradeoff:** latência HTTP por desacoplamento (modelo atualiza sem rebuild do Flink).

### 4. Feature store em Redis (Sprint 4.B)
- Worker, após efetivar, atualiza features rolling no Redis (count_1h, valores_24h, valores_30d) por CPF origem.
- ML service lê do Redis no /predict — features reais, não placeholders.
- Latência típica do lookup Redis: <2ms (pipeline batching).
- Idempotência via SET NX EX (1h) — replay de Kafka não duplica contadores.
- Best-effort: se Redis cair, /predict usa defaults (não derruba decisão).
- **Tradeoff:** estado externo vs simplicidade — escolho externo pra escalar horizontalmente
  o ML service (qualquer worker do gunicorn consulta o mesmo Redis).

### 5. Validação de saldo no Worker (Sprint 4.A)
- ML aprovou + regras aprovaram + Worker checa saldo na transação Postgres.
- Se saldo < valor+taxa: marca `status='COMPENSADA'`, motivo `SALDO_INSUFICIENTE`,
  registra idempotência e segue. Cliente vê status final via GET /transferencia/{id}.
- Calculado por `SUM(C - D)` na mesma transação — sem race condition.

### 4. Observabilidade obrigatória, não decorativa
- OpenTelemetry trace propagada via Kafka header
- Trace completa: Angular → API → Kafka → Flink → ML → Worker → Postgres no Jaeger
- Métricas Prometheus em todos os serviços
- Grafana dashboard pré-configurado

## Demo ao vivo (1 min)

1. `make demo` no terminal lateral.
2. 50 transferências legítimas → todas aprovadas, p95 ~ 200ms (mostro no Grafana).
3. Burst: 8 transferências de R$4.999 do mesmo CPF em 30s.
4. A partir da 4ª, score sobe acima do threshold → REJEITADA.
5. Painel ops mostra alerta em tempo real via SSE.
6. Worker **não** processa as rejeitadas — saldo do atacante não é debitado, vítimas (destinos) não recebem.

## Perguntas que você quer ouvir

- "Como você faz deploy de novo modelo sem downtime?"
  → **Shadow mode**: Flink chama dois modelos, registra ambas predições, só uma decide. A/B online sem risco. `X-Model-Version` em todo evento.

- "E LGPD?"
  → CPF é hasheado com salt rotativo antes de entrar no Kafka. Logs mascarados. PII só na API e no Postgres, com criptografia em repouso.

- "Como você escalaria?"
  → Particionamento Kafka por hash do CPF; Flink scaleia consumindo as partições; ML é stateless atrás de Gunicorn workers; Postgres com read-replica para o feature store warm.

- "Como você sabe se o modelo está funcionando?"
  → PSI mensal nos features; recall medido em janela móvel comparando rejeições com chargebacks reportados; alertas em drift > 0.2.

## O que NÃO contar

- Que o BankMore tem 3 versões anteriores quebradas.
- Quanto tempo levou.
- Que os schemas Avro foram a parte mais demorada (parece bobeira mas dá calo).
