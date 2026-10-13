# ML Service — Fraud Scoring

XGBoost treinado no build da imagem Docker e servido via Flask + Gunicorn (Sprint 3), agora com ciclo de vida de modelo: registro, retreino reproduzível, modo sombra, drift por PSI e portão de promoção ([ADR 0023](../docs/adr/0023-ciclo-de-vida-do-modelo-de-fraude.md)).

> **Dados sintéticos.** Tudo aqui roda sobre transações geradas por `dados.py`. Os números mostram o mecanismo e as trocas, não a eficácia de um antifraude real.

## Componentes

| Arquivo | O que faz |
|---|---|
| `dados.py` | Dataset sintético com seed explícita e cenários (`base`, `nova_fraude` e misturas como `base+nova_fraude`). Os conjuntos de avaliação usam um fluxo aleatório que nenhuma seed de treino reproduz. |
| `train.py` | Treino (IsolationForest de baseline + XGBoost). No `docker build`, registra a v1 já em produção. |
| `retreinar.py` | Retreino reproduzível: gera o dataset, treina e registra a versão como **candidata**. |
| `registro.py` | Registro de modelos em arquivos: versões imutáveis, ficha, estados, histórico e reversão. |
| `portao.py` + `criterio_promocao.json` | Portão de promoção: o candidato só vira produção se o critério deixar. |
| `drift.py` | PSI das features e do score contra a referência do treino. |
| `app.py` | Flask: `/predict`, sombra, drift e troca de modelo sem redeploy. |
| `scripts/demo_ciclo.py` | O ciclo inteiro de ponta a ponta; é o que o CI roda. |
| `scripts/experimento_seeds.py` | Gera a tabela de candidatos do ADR 0023, com as seeds listadas. |
| `tests/` | 48 testes. |

## Ciclo de vida do modelo

```
retreinar.py ──► candidato ──► sombra (recomendada) ──► portão ──► produção ──► reverter
                (ficha com     (pontua, não decide)     (laudo)    (o serviço   (volta para a
                 hashes)                                            recarrega)   anterior)
```

### Rodar sem Docker

No diretório `ml/`, com Python 3.11 ou 3.12:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt                    # Windows: .venv\Scripts\pip.exe
.venv/bin/python -m unittest discover -s tests -t .          # Windows: .venv\Scripts\python.exe
.venv/bin/python scripts/demo_ciclo.py                        # o ciclo completo, alguns minutos
.venv/bin/python scripts/experimento_seeds.py                 # a tabela do ADR, ~3 min
```

### No container

Com a stack de pé (`make up`):

```bash
docker exec bankmore-fraud-ml python registro.py listar
docker exec bankmore-fraud-ml python retreinar.py --versao xgboost-v2 --cenario base+nova_fraude
docker exec bankmore-fraud-ml python registro.py sombra xgboost-v2
# ...tráfego passa; ver /sombra, /drift e os alertas no Prometheus...
docker exec bankmore-fraud-ml python portao.py xgboost-v2              # laudo; saída 0 = aprovado
docker exec bankmore-fraud-ml python portao.py xgboost-v2 --promover
docker exec bankmore-fraud-ml python registro.py reverter "motivo do incidente"
docker exec bankmore-fraud-ml python registro.py sem-sombra "motivo"
```

O serviço confere o registro a cada 5 s (`ML_RECARGA_S`), então promover e reverter não exigem redeploy. As promoções sobrevivem a restart do container. Recriar o container volta ao estado da imagem; em produção, o registro iria para um volume ou um storage de objetos.

### Ficha de cada versão

`registro/<versao>/ficha.json` guarda:

- **dados:** cenário, seed, n e hash dos dados (números arredondados a 6 casas, para valer no Windows e no Linux);
- **reprodutibilidade:** hash do código de treino, versões das bibliotecas, plataforma e o comando que refaz o treino;
- **régua:** hash da régua de promoção, que cobre o critério, o gerador da avaliação e o `portao.py`;
- **operação:** métricas, limiar de operação e referência de drift.

Na mesma plataforma, com as mesmas bibliotecas, o mesmo comando dá os mesmos dados e as mesmas métricas. O cenário `base` com seed 42 reproduz o dataset do `train.py` anterior; conferido byte a byte no Windows.

### Portão de promoção

- **Critério v1** (`criterio_promocao.json`): recall com **1% de falso positivo** sobre as transações legítimas (Pix, TED e TEF), nos cenários `base` e `nova_fraude`.
- **Regra:** o candidato não pode ser pior que a produção em nenhum conjunto.
- **Laudo:** fica em `registro/<versao>/laudo-*.json`. Para informação, ele traz também:
  - o IC95 da diferença de recall (bootstrap pareado);
  - o recall com 0,1% e 0,3% de falso positivo;
  - os números no limiar de cada modelo e no **0,95 que os consumidores usam** (o Pix API e o PyFlink barram com `score >= 0,95`).
- **Regra estatística (opcional):** com `regra_estatistica` no critério, a tolerância passa a valer sobre o limite inferior do IC.

O que o mecanismo garante: se a régua mudar depois do treino do candidato, o portão se recusa a avaliar, e a promoção exige um laudo emitido com a régua da ficha. O que **não** garante: que ninguém escolha a régua depois de ver resultados. Isso é governança; detalhes no ADR 0023.

### Modo sombra

A versão em sombra pontua a mesma transação na mesma requisição, **depois** da decisão. Ela é síncrona e soma um predict à latência. Nunca decide. Uma falha dela, ao carregar ou ao pontuar, não afeta a produção. As discordâncias aparecem em três lugares:

- `ml_sombra_discordancias_total{direcao, limiar="modelo|consumidor"}`;
- `GET /sombra`;
- `registro/sombra/<versao>.jsonl`, sem `cpfOrigem`, com valores arredondados, hora ao minuto e no máximo 5 MB por versão (`ML_SOMBRA_LOG_MAX_BYTES`). Apague junto com a versão.

### Drift

O serviço guarda as últimas `ML_DRIFT_JANELA` transações (padrão 5.000). A cada `ML_DRIFT_A_CADA` predições (padrão 100), com no mínimo 1.000 na janela, calcula o PSI de cada feature e do score contra a referência da ficha:

- **features contínuas:** por decis do treino;
- **features discretas e categóricas:** por valor.

Features que vieram de placeholder (sem feature store) ficam fora do cálculo e são contadas em `ml_feature_placeholder_total`. Os resultados saem em `ml_feature_psi{feature=...}`, `ml_score_psi` e `GET /drift`.

Alertas em `infra/prometheus/alerts/ml.yml`. Os alertas de drift seguem a regra de bolso do mercado:

| Alerta | Dispara quando |
|---|---|
| `MlDriftAlto` | PSI > 0,25 por 15 min |
| `MlDriftModerado` | PSI > 0,10 por 1 h |
| `MlScoreDrift` | PSI do score > 0,25 |
| `MlSombraDiscordanciaAlta` | no 0,95, a sombra decidiria diferente em mais de 5% |
| `MlSombraFalhando` | falha da sombra |
| `MlRecargaFalhando` | falha ao recarregar o registro |

O compose não tem Alertmanager; os alertas aparecem em http://localhost:9090/alerts.

## O que os experimentos mostraram

Com 100 mil transações por treino (`scripts/demo_ciclo.py` e `scripts/experimento_seeds.py`):

- **Drift:** quando a população muda, o PSI vai de 0,009 para 0,54. A v1 cai de 36 para 20 fraudes barradas em 40.
- **Ruído:** o critério v1 (tolerância zero) reprova até a própria receita da v1 com outra seed (8 de 8). Uma fraude vale 0,125 ponto no conjunto de avaliação.
- **Retreino com dados novos:** perde 3,6 a 4,9 pontos no padrão antigo e ganha 32 no cenário novo (população nova, 40% das fraudes no padrão F6). O portão reprova.
- **Mistura de dados antigos e novos:** perde 1,4 a 2,9 pontos no padrão antigo (IC95 da v3 entre −3,2 e −0,9) e ganha 29 a 32 no novo. O critério v1 reprova; a troca é real.
- **No ponto de operação, a troca cresce:** no 0,95 dos consumidores, a v4 da demo perde 5,4 pontos no padrão antigo e ganha 21,6 no novo, nos conjuntos de avaliação.
- **Critério v2:** é decisão em aberto. A demo mostra o mecanismo com um critério v2 hipotético, escolhido depois de ver a v3. O critério do repositório continua o v1.

## Métricas de treino do modelo base

| Métrica | IsolationForest (baseline) | XGBoost |
|---|---|---|
| ROC-AUC | 0.947 | 0.999 |
| Average Precision (PR-AUC) | 0.298 | 0.973 |

O AUC perto de 1 vem de padrões sintéticos fáceis. Ele não diz nada sobre produção; por isso o portão compara recall com falso positivo fixo.

| Configuração | Valor |
|---|---|
| n_amostras | 100.000 |
| fração fraude | 2% |
| `scale_pos_weight` | 49 |
| threshold pra recall ≥ 0.85 | 0.991 |

Quem barra o Pix são os consumidores, com `FRAUDE_THRESHOLD` / `ML_REJEITAR_THRESHOLD` = 0,95 no compose, entre o 0,7 agressivo e o 0,991 do treino. Esse corte captura fraudes claras (R$ ≥ 30k → score 0,99) sem bloquear valor alto legítimo (R$ 10k → score 0,83 → APROVADA + ALERTA). O `decisao_recomendada` do `/predict` usa o limiar da ficha.

## Features que o modelo usa

| Feature | Origem | Status atual |
|---|---|---|
| `valor` | request | OK |
| `tipo` (PIX/TED/TEF, one-hot) | request | OK |
| `hora_do_dia` | event timestamp | OK |
| `dow` | event timestamp | OK |
| `count_tx_cpf_1h` | MapState do PyFlink (60s aprox) | parcial (Sprint 4 separa o state) |
| `is_autotransferencia` | regra dura já filtrou antes | sempre 0 no /predict |
| `valor_medio_cpf_24h` | feature store | **placeholder** = valor sem histórico no Redis |
| `valor_p95_cpf_30d` | feature store | **placeholder** = valor × 2 sem histórico no Redis |

## Padrões de fraude no dataset sintético

| Pattern | Descrição |
|---|---|
| F1 | valor > R$ 15.000 (acima do p99 da população normal) |
| F2 | ≥ 5 transações na última hora |
| F3 | noturno (0-5h) + valor > R$ 3.000 |
| F4 | valor / valor_medio_24h > 10x |
| F5 | autotransferência (mesma origem/destino) |
| F6 | só no cenário `nova_fraude`: valor moderado, de dia, 4 a 8x a média de 24h, 2 a 4 Pix na última hora |

Em produção, o dataset real substitui esse sintético; os padrões F2, F4 e F6 dependem do feature store completo.

## Endpoints

### `POST /predict`
```bash
curl -X POST http://localhost:5003/predict -H 'Content-Type: application/json' -d '{
  "features": {
    "valor": 15000, "tipo": "TED",
    "hora_do_dia": 3, "dow": 2,
    "count_tx_cpf_1h": 1,
    "valor_medio_cpf_24h": 200,
    "is_autotransferencia": 0,
    "valor_p95_cpf_30d": 500
  }
}'
```
```json
{
  "score": 0.9998,
  "decisao_recomendada": "REJEITAR",
  "modelo_versao": "xgboost-v1",
  "threshold": 0.991,
  "latencia_ms": 62.55
}
```
A resposta não muda com a sombra: só a produção pontua o que volta.

### `GET /health`
```json
{ "status": "healthy", "model_loaded": true, "model_version": "xgboost-v1",
  "shadow_version": null, "threshold": 0.991, "registro": true,
  "registro_pede": { "producao": "xgboost-v1", "sombra": null } }
```

### Outros

| Rota | O que mostra |
|---|---|
| `GET /metrics` | Formato Prometheus: predições, latência, distribuição de score, versões carregadas, sombra, PSI, recargas e placeholders. |
| `GET /metrics/json` | O JSON antigo (contadores e métricas de treino), mantido por compatibilidade. |
| `GET /modelos` | Registro: produção, sombra, anteriores, histórico recente e o que está carregado. Responde 503 se o índice estiver ilegível. |
| `GET /sombra` | Predições e discordâncias da sombra, nos dois limiares. |
| `GET /drift` | PSI de cada feature e do score, com nível (estável, moderado, alto) e as features fora do cálculo. |

O Gunicorn roda 1 processo com 4 threads, então métricas, sombra e drift são do serviço todo.

## Decisões pendentes

- **Critério v2:** aceitar ou não a troca entre o padrão antigo e o golpe novo. Também é preciso definir a tolerância (acima do piso de ruído, de preferência sobre o IC) e o ponto de falso positivo em que se mede (ADR 0023).
- **Uma fonte para o ponto de operação:** os consumidores usam o `decisao_recomendada`, ou o critério mede no 0,95 (ADR 0023).
- **Dados:** substituir o dataset sintético por um dump anonimizado e rotulado de produção. O recall exige fraude confirmada, que chega com atraso.
- **Feature store completo:** Redis para 1h, Postgres warm para 30d.
- **Async I/O** no PyFlink chamando o ML (hoje síncrono, bloqueia slot).
- **Agendamento do retreino**, só quando houver dado real.
- **Registro** num volume ou storage de objetos, com trava entre processos.
