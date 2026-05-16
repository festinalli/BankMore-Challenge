# Handoff — Sprint 4.D + 4.C

> **Para a próxima sessão começar do zero sem precisar reler 6h de conversa.**
> Leia este doc + `CASE_TOP_PLAN.md` + `README.md` e você tem tudo pra atacar.

## 1. O que está pronto (não mexer)

- ✅ **Sprint 1**: stack 100% Docker, fluxo Solicitada → Worker
- ✅ **Sprint 2**: detector com state, persistência de status no Postgres
- ✅ **Sprint 2.5**: PyFlink real (JVM + KeyedProcessFunction + RocksDB + EXACTLY_ONCE)
- ✅ **Sprint 3**: XGBoost (ROC-AUC 0.9993) treinado no build, Flask `/predict`, decisão híbrida regras+score
- ✅ **Sprint 4.A**: validação de saldo no Worker → COMPENSADA se insuficiente
- ✅ **Sprint 4.B**: feature store Redis populado pelo Worker, consumido pelo ML

**Branch ativa:** `case-top` no `https://github.com/festinalli/-BankMore-Challenge`
**Último commit:** `0a7dc69 chore(sprint4): compose Redis pro worker + 6º cenário e2e`

**`make e2e` valida 6 cenários, todos passando.**

## 2. Retomada da stack (commands)

```bash
# Se você já tem o repo localmente:
cd ~/Downloads/_bankmore_git/BankMore_CaseTop
git pull origin case-top
make up && make seed && make e2e

# Se está começando de máquina nova:
git clone https://github.com/festinalli/-BankMore-Challenge.git _bankmore_git
cd _bankmore_git
git checkout case-top
cd BankMore_CaseTop
make pyflink-deps     # baixa apache-flink-libraries-1.18.1.tar.gz (220MB) no host
make up               # builda imagens + sobe 13 containers
make seed             # cria Alice (R$10k) e Bob (R$20k)
make e2e              # roda 6 cenários
```

Estado esperado depois: 13 containers up, `✅ todos os cenários e2e passaram`.

## 3. O que falta (Sprint 4.D + 4.C)

### Sprint 4.D — Painel ops `/ops/fraude` no Angular (SSE)

**Objetivo:** painel visual em tempo real mostrando alertas/rejeições, pra demo de entrevista.

**Decisões já tomadas:**
- SSE (Server-Sent Events) em vez de WebSocket. Mais simples, unidirecional, suficiente pro caso.
- Endpoint vai no `ContaCorrente.Api` (porta 5000) — já tem Postgres connection e está sempre up.
- Consome **2 tópicos Kafka**: `fraude.alerta` + `transferencia.rejeitada` (em paralelo).
- Sem autenticação nesse endpoint na v1 (Sprint 5 adiciona role=ops).

**Plano de implementação:**

1. **`src/BankMore.ContaCorrente.Api/Controllers/FraudeOpsController.cs`** (novo)
   ```
   [HttpGet("/api/admin/fraude/stream")]
   public async Task Stream(CancellationToken ct)
   {
       Response.Headers["Content-Type"] = "text/event-stream";
       Response.Headers["Cache-Control"] = "no-cache";
       // Cria 2 consumers Kafka (group ID "fraud-ops-{guid}")
       // poll → escreve `data: {json}\n\n` no Response.Body
       // até ct.IsCancellationRequested
   }
   ```
   Usar **Confluent.Kafka** diretamente (não KafkaFlow) — KafkaFlow é overkill aqui;
   só queremos consumer simples.

2. **`src/BankMore.ContaCorrente.Api/BankMore.ContaCorrente.Api.csproj`** adicionar:
   ```xml
   <PackageReference Include="Confluent.Kafka" Version="2.4.0" />
   ```

3. **`appsettings.json`** + **compose** ganham `Kafka__Broker=kafka:29092` na ContaCorrente.Api.

4. **Frontend Angular** novo componente `frontend/src/app/features/ops/fraude.component.ts`:
   ```
   ngOnInit() {
     this.es = new EventSource('http://localhost:5000/api/admin/fraude/stream');
     this.es.onmessage = e => this.alerts.unshift(JSON.parse(e.data));
   }
   ```
   - Lista de últimos 50 alertas (in-memory)
   - Cards com cor (vermelho=REJEITADA, amarelo=ALERTA)
   - Mostra: `id curto, cpfOrigem mascarado, valor, motivos, score, modelo_versao, decididoEm`
   - Botão "limpar" + filtros opcionais por decisão

5. **`frontend/src/app/app.routes.ts`** adicionar rota `/ops/fraude` (sem `canActivate` na v1).

6. **README + storyline** atualizar.

7. **e2e cenário 7** (opcional): script abre conexão SSE via curl, dispara cenário 5 (R$30k → REJEITADA), assert que recebeu evento pelo stream.

**Cuidado conhecido:**
- CORS já permite qualquer origem (Sprint 1). SSE funciona.
- Cada conexão SSE cria 2 consumers Kafka. Limitar paralelismo (max 10 conexões? rate limit no controller? Sprint 5).
- `Response.Body.FlushAsync()` após cada `data:` line — senão buffer no Kestrel atrasa.

---

### Sprint 4.C — Async I/O no PyFlink

**Objetivo:** desbloquear o slot do TaskManager durante chamadas HTTP pro ML. Hoje `urllib.request` síncrono bloqueia o thread durante 60ms+ (latência típica do `/predict`).

**Decisões já tomadas:**
- PyFlink 1.18 **NÃO tem AsyncFunction nativo no Python API** (só Java). 
- Soluções avaliadas:
  1. ❌ Implementar AsyncIO em Java + wrapper Python — caro, foge do escopo Python-only.
  2. ❌ Reescrever em Java — perde "pyflink" da história.
  3. ✅ **Batch + ThreadPoolExecutor**: o `process_element` enfileira a chamada e processa
     em N threads paralelas dentro do operator. Não é "async I/O" puro mas dá efeito
     equivalente (slot fica livre logo). É o padrão recomendado pela comunidade.
  4. ✅ **Alternativa simples**: aumentar `parallelism` do operator. Mais slots → mais
     processamento paralelo natural. Não tira a chamada síncrona mas escala horizontalmente.

**Plano (opção 3 — ThreadPoolExecutor):**

1. **`pyflink/fraud_detector_job.py`** — em `FraudDecider.open()`:
   ```python
   from concurrent.futures import ThreadPoolExecutor
   self._http_pool = ThreadPoolExecutor(max_workers=8)
   ```
   
2. **`_consultar_ml`** → submete future + aguarda com timeout:
   ```python
   future = self._http_pool.submit(self._do_http_call, features, cpf_origem)
   try:
       return future.result(timeout=ML_TIMEOUT_SECONDS)
   except TimeoutError:
       return None, ""
   ```
   
   **Problema:** isso **não** libera o thread do operator — o `result()` ainda bloqueia.
   Pra benefício real, mudar de `process_element` (sync) pra um buffer + janela tumbling
   pequena (`window(Time.milliseconds(100)) → process_window(batch)` que chama N requests
   em paralelo).

3. **Opção mais pragmática (recomendada):**
   - Aumentar `env.set_parallelism(4)` (de 1) — múltiplos slots processam em paralelo
   - Aumentar `KafkaConsumer` partitions já configurado em 3 → match
   - Medir antes/depois com `wrk` ou loop curl batido

**Métricas a coletar:**
- Latência p95 do `process_element` antes/depois
- Throughput (msgs/s) antes/depois
- `% slots ocupados` no Flink UI

**Alternativa real-async** (só registrar, não fazer agora):
- Refatorar pra `KafkaSource → KeyedProcessFunction (filtra regras duras) →
  AsyncWaitOperator (Java) → KafkaSink`. Mas isso quebra "tudo em Python".

## 4. Decisões abertas pra próxima sessão decidir

- **Sprint 4.D:** o painel ops vai ficar no mesmo Angular do cliente ou em app separado `frontend-ops/`? **Preliminar:** mesmo Angular, rota `/ops/fraude`, sem guard (v1).
- **Sprint 4.C:** opção 2 (parallelism) ou opção 3 (ThreadPool)? **Preliminar:** começa com (2) — barato, mede; se não bastar, (3).
- Adicionar Sprint 4.E (Prometheus/Grafana) junto ou deixar pra Sprint 5? **Preliminar:** Sprint 5 — D+C já entrega muito.

## 5. Estrutura atual do código (mapa rápido)

```
BankMore_CaseTop/
├── README.md                                    ← contexto + diagramas
├── CASE_TOP_PLAN.md                             ← roadmap dos 4 sprints
├── docs/
│   ├── HANDOFF_SPRINT_4_DC.md                   ← este arquivo
│   ├── storyline-entrevista.md                  ← pitch pra entrevista
│   └── legado.md                                ← (não criado ainda)
├── Makefile                                     ← targets: env, up, down, e2e, seed, etc
├── scripts/e2e.sh                               ← 6 cenários assertados
│
├── infra/
│   ├── compose/docker-compose.yml               ← 13 services (sprint 4.D adicionará nada no compose;
│   │                                              4.C tampouco. Sprint 4.E adiciona prometheus + grafana)
│   └── db/init.sql                              ← schema canônico Postgres
│
├── contracts/avro/                              ← schemas (não em uso ainda — Sprint 5)
│
├── src/                                         ← .NET 8 LTS
│   ├── BankMore.ContaCorrente.Api/              ← onde vai o FraudeOpsController (Sprint 4.D)
│   ├── BankMore.ContaCorrente.Application/      ← handlers MediatR
│   ├── BankMore.ContaCorrente.Domain/           ← entities + interfaces
│   ├── BankMore.ContaCorrente.Infrastructure/   ← Dapper repository
│   ├── BankMore.Transferencia.Api/              ← persiste SOLICITADA + publica Kafka
│   ├── BankMore.Transferencia.Application/      ← EfetuarTransferenciaHandler
│   ├── BankMore.Transferencia.Domain/           ← entity + IRepository
│   ├── BankMore.Transferencia.Infrastructure/   ← Dapper repository
│   └── BankMore.Tarifas.Worker/
│       ├── Program.cs                           ← Redis + Kafka + MediatR DI
│       ├── Handlers/
│       │   ├── TarifaConsumer.cs                ← efetiva + valida saldo + popula Redis (Sprint 4.A+B)
│       │   └── RejeicaoConsumer.cs              ← atualiza status REJEITADA
│       └── Services/FeatureStore.cs             ← StackExchange.Redis (Sprint 4.B)
│
├── pyflink/                                     ← detector
│   ├── fraud_detector_job.py                    ← onde mexer no Sprint 4.C
│   ├── fraud_detector.py                        ← versão Python puro (fallback, não em uso)
│   ├── Dockerfile.flink                         ← PyFlink real (em uso)
│   ├── Dockerfile                               ← Python puro (não em uso)
│   ├── fetch_pyflink_libs.sh                    ← baixa apache-flink-libraries
│   └── wheels/                                  ← apache-flink-libraries-1.18.1.tar.gz (gitignored)
│
├── ml/                                          ← XGBoost service
│   ├── train.py                                 ← roda no docker build
│   ├── app.py                                   ← Flask /predict (Redis lookup)
│   ├── Dockerfile                               ← treina + serve
│   └── requirements.txt
│
├── frontend/                                    ← Angular 21 (onde vai o /ops/fraude no Sprint 4.D)
│   └── src/app/
│       ├── features/login/                      ← existe
│       ├── features/dashboard/                  ← existe
│       ├── features/transferencia/              ← existe
│       ├── features/extrato/                    ← existe
│       └── features/ops/                        ← criar no Sprint 4.D
│
└── tests/BankMore.ContaCorrente.Application.Tests/   ← 9 xUnit, todos verdes
```

## 6. Onde estão os logs úteis

```bash
# Logs em tempo real:
docker logs -f bankmore-fraud-detector       # PyFlink Python stdout
docker logs -f bankmore-fraud-ml              # /predict latências
docker logs -f bankmore-tarifas-worker        # efetivações + COMPENSADA
docker logs -f bankmore-transferencia-api     # SOLICITADA criadas

# Log do mini-cluster Flink (decisões, checkpoints):
docker exec bankmore-fraud-detector bash -c \
  'tail -100 /opt/flink/log/flink-root-python-*.log'

# Postgres:
make psql
# > SELECT id, status, motivo, valor, score_fraude, modelo_versao FROM transferencia ORDER BY solicitada_em DESC LIMIT 10;

# Redis (feature store):
docker exec bankmore-redis redis-cli
# > KEYS feat:*
# > GET feat:11111111111:count_1h
# > LRANGE feat:11111111111:valores_24h 0 -1

# Tópicos Kafka:
docker exec bankmore-kafka kafka-console-consumer \
  --bootstrap-server kafka:29092 \
  --topic fraude.alerta --from-beginning --max-messages 5
```

## 7. URLs de UI

- ContaCorrente API: http://localhost:5000/swagger
- Transferência API: http://localhost:5001/swagger
- Kafka UI: http://localhost:8080
- Flink JM: http://localhost:8082
- ML Service: http://localhost:5003/health, /metrics
- Schema Registry: http://localhost:8085
- Frontend: `cd frontend && npm install && ng serve` → http://localhost:4200

## 8. Identidade git (já configurada localmente)

```
git -C ~/Downloads/_bankmore_git config user.email "fabiofestinalli@gmail.com"
git -C ~/Downloads/_bankmore_git config user.name  "Fabio Festinalli"
```

(Local apenas, sem mexer no global.)

## 9. Padrão de commits (manter)

Convencional commits + Co-authored-by no fim:

```
feat(escopo): título curto até 72 chars

Body em 2-3 parágrafos descrevendo o "por quê", não só o "o quê".
Quando relevante: tradeoffs, alternativas avaliadas, limitações.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

3 commits por sprint costuma funcionar:
1. `feat(área-principal)` — entrega central
2. `feat(área-secundária)` ou `chore(infra)` — plumbing
3. `chore(sprintN)` — compose + e2e + README + docs

## 10. Plano sugerido para a sessão

```
1. (5min)  git pull + make up + make e2e — confirmar tudo verde
2. (60min) Sprint 4.D: FraudeOpsController + Angular /ops/fraude
   - controller .NET com 2 consumers Kafka
   - componente Angular com EventSource + cards
   - cenário 7 e2e (opcional)
3. (45min) Sprint 4.C: parallelism + medições
   - env.set_parallelism(4)
   - rodar burst no e2e, medir
   - se p95 não melhorou: ThreadPoolExecutor no _consultar_ml
4. (15min) commits + push + README atualizado
```
