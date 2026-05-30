# 0018 — Sprint 9: Antifraude inline no PIX (scoring síncrono)

**Status:** Aceito · **Data:** 2026-05-30

## Contexto

A Sprint 8 entregou o PIX real (DICT, SPI/ISO 20022, MED, QR, Automático, NFC,
Open Finance), mas sem antifraude — qualquer pagamento com chave válida liquidava.
O projeto já tem um pipeline de fraud detection (PyFlink + XGBoost, `fraud-ml`)
cobrindo `transferencia.solicitada`. A Sprint 9 conecta os dois pilares: o PIX
passa a ser avaliado pelo mesmo modelo, **antes** de liquidar.

## Decisão: scoring síncrono inline (não streaming)

O PIX é instantâneo (SLA de liquidação <10s). Diferente da transferência (que
passa pelo Kafka + PyFlink de forma assíncrona), o PIX **não pode** esperar um
pipeline de streaming decidir — a análise precisa ser síncrona e rápida, inline
no caminho de liquidação. É assim que as fintechs fazem de verdade: scoring
inline antes de mandar pro SPI.

Fluxo no `PixLiquidacaoService`, entre a checagem de auto-transferência e o envio
do pacs.008 ao SPI:

```
resolve chave (DICT)
  → auto-transferência? rejeita
  → ANÁLISE DE FRAUDE (status ANALISE_FRAUDE):
      conta tx recentes do CPF (burst) → chama fraud-ml /predict
      score >= threshold? → REJEITADO (não vai ao SPI, não liquida)
  → monta pacs.008 → SPI → liquida movimentos
```

### Reuso do fraud-ml (não duplica modelo)

O `pix-api` chama o **mesmo** `/predict` do `fraud-ml` (XGBoost) que o
fraud-detector PyFlink usa. Um modelo, duas portas de entrada (streaming pra
transferência, inline pra PIX). Garante decisões consistentes entre canais.

### Correção de timezone já nascida certa

O `FraudeClient` computa `hora_do_dia`/`dow` em **America/Sao_Paulo**, não UTC.
Esse foi exatamente o bug que detectamos no fraud-detector PyFlink (Sprint 7):
o modelo foi treinado com hora local brasileira, e usar UTC gerava falsos
positivos à noite (22h BRT = 01h UTC, que o modelo aprendeu como madrugada
suspeita). O PIX já nasce com a conversão correta.

### Fail-open

Se o `fraud-ml` cair (timeout 2s), o `Avaliar` retorna null e o pagamento segue
só com as regras duras (auto-transferência, valor inválido). Indisponibilidade
do scoring não derruba PIX legítimo — a disponibilidade do pagamento instantâneo
tem precedência sobre o enriquecimento por ML.

### Off-by-one do burst (corrigido)

A contagem de transações recentes (`count_tx_cpf_1h`) é feita **antes** de
inserir o pagamento atual. Antes, o próprio pagamento inflava o count em 1,
disparando burst falso. O modelo é sensível: `count >= ~6` numa hora já pesa
forte no score.

## Persistência e auditoria

`pix_pagamento` ganhou `score_fraude NUMERIC(5,4)` e `modelo_versao TEXT`. Todo
pagamento avaliado registra o score, mesmo quando aprovado — trilha pra análise
posterior e tuning de threshold. Novo status `ANALISE_FRAUDE` na state machine.

## Configuração

| Env | Default | Efeito |
|-----|---------|--------|
| `FRAUDE_HABILITADO` | `true` | liga/desliga o scoring inline |
| `FRAUDE_THRESHOLD`  | `0.95` | score acima do qual rejeita |
| `FRAUDE_ML_URL`     | `http://fraud-ml:5003` | endpoint do modelo |

## Validação

`make e2e-pix` — fluxo 9 novo: PIX de R$ 50.000 → score 0.9999 → **REJEITADO**
antes do SPI, sem liquidar (saldo do destino inalterado, `pacs008_xml` nulo
confirmando que nem chegou a montar a ordem de pagamento). Os 8 fluxos legítimos
continuam verdes.

## Consequências

- ✅ PIX protegido pelo mesmo modelo XGBoost do resto do sistema
- ✅ Decisão síncrona <2s, compatível com o SLA do PIX
- ✅ Score auditado em todo pagamento; status `ANALISE_FRAUDE` rastreável
- ✅ Timezone correto desde o início (lição da Sprint 7 aplicada)
- ✅ Fail-open: ML indisponível não bloqueia pagamento legítimo
- ⚠ **Modelo agressivo com burst**: `count >= ~6/h` pesa muito. Pra PIX (onde
  fazer vários pagamentos por hora é normal), pode gerar falsos positivos.
  Tuning do threshold por canal ou retreino com dados de PIX real é evolução.
- ⚠ **Sem feedback loop**: rejeições não realimentam o treino. Sprint futura
  pode publicar as decisões pra um pipeline de re-treino.
- ⚠ **Scoring só na iniciação**: análise pós-liquidação em janela (padrões
  temporais via PyFlink) complementaria — publicar `pix.liquidada` no Kafka
  pro fraud-detector enriquecer o feature store sem bloquear o pagamento.
