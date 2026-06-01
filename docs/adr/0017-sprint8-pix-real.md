# 0017 — Sprint 8: PIX real (DICT + SPI/ISO 20022 + MED + QR + Automático + NFC + Open Finance)

**Status:** Aceito · **Data:** 2026-05-30

## Contexto

Até a Sprint 7, "PIX" no BankMore era só um valor de enum (`TipoTransferencia.PIX`)
com tarifa zero. Não havia nada da tecnologia real do arranjo PIX. A Sprint 8
implementa o PIX como ele funciona de verdade nas fintechs, num bounded context
próprio (`BankMore.Pix`) + um simulador do BACEN (`bacen-sim`).

**O que NÃO é:** conexão com o BACEN real. Isso exige ISPB homologado, certificado
ICP-Brasil (mTLS na RSFN — Rede do Sistema Financeiro Nacional) e processo formal de
homologação. O `bacen-sim` simula o lado do regulador com fidelidade de protocolo.

## Decisão

### Topologia: bounded context PIX + bacen-sim dedicado

```
  pix-api (5006)  ──HTTP──>  bacen-sim (5005)
   │                          ├── DICT  (resolução/registro de chaves)
   │                          └── SPI   (liquidação ISO 20022)
   ├── Clean Arch (Domain/Application/Infrastructure/Api)
   ├── CQRS + MediatR
   └── liquidação contábil → movimentos (D origem / C destino) na mesma TX
```

`bacen-sim` é um serviço separado (não um mock in-process) **de propósito**: reflete
a topologia real onde PSP e BACEN são organizações distintas que se comunicam por
mensageria. Cada lado tem sua própria implementação ISO 20022 — não compartilham
código (não há projeto `Shared.Iso20022`), exatamente como na vida real.

### 8.A — DICT + SPI (ISO 20022)

**DICT** (Diretório de Identificadores de Contas Transacionais): mapeia chave
(CPF/CNPJ/EMAIL/TELEFONE/EVP) → conta (ISPB, titular). Endpoints REST de
resolução, registro, remoção e claims (portabilidade/reivindicação). No bacen-sim
o claim resolve imediatamente (simplificação da janela real de 7 dias úteis).

**SPI** (Sistema de Pagamentos Instantâneos): liquida via mensagens ISO 20022:
- `pacs.008.001.08` (FIToFICstmrCdtTrf) — ordem de pagamento
- `pacs.002.001.10` (FIToFIPmtStsRpt) — status report (ACSC/RJCT + reason code)
- `pacs.004.001.09` (PmtRtr) — devolução

XML gerado com namespaces e hierarquia fiéis ao schema real. Latência de
liquidação simulada (50–400ms) demonstra o SLA <10s sem travar a demo. Reason
codes do Manual de Padrões do SPI: AC03 (conta inválida), AM02 (valor), AB09
(instituição), FF01 (formato).

### 8.B — EndToEndId + liquidação contábil

EndToEndId no formato BACEN: `E + ISPB(8) + AAAAMMDDHHMM + 11 chars`. O mesmo id
viaja no `EndToEndId` do pacs.008 e volta no pacs.002.

A liquidação cria movimentos `D` (origem) e `C` (destino) na **mesma transação** —
o saldo é `SUM(movimento)` na view `saldo_conta`, então a atomicidade do par
débito/crédito garante consistência contábil. As mensagens pacs.008/pacs.002 são
persistidas em `pix_pagamento` para auditoria.

### 8.C — BR Code EMVCo

QR Code no padrão EMVCo MPM com os campos do arranjo PIX (TLV: Tag-Length-Value).
Campo 26 carrega o GUI `br.gov.bcb.pix` + chave (estático) ou URL do payload
(dinâmico). Campo 63 é o **CRC16-CCITT** (poly 0x1021, init 0xFFFF) do payload.
- Estático: chave + valor opcional, reutilizável
- Dinâmico/CoBV: txid único (25 chars), uso único, com vencimento opcional

### 8.D — MED

Mecanismo Especial de Devolução com state machine: `SOLICITADA → BLOQUEADO →
DEVOLVIDO | LIBERADO | NEGADO`. Bloqueio cautelar imediato do recurso. SLA por
motivo (11 dias golpe confirmado / 80 dias análise). DEVOLVIDO envia `pacs.004`
ao SPI (reason MD06=fraude/BE08=erro) e estorna os movimentos.

### 8.E — PIX Automático (jun/2025)

Recorrência autorizada por consentimento. State machine: `CRIADO → AUTORIZADO →
CONSUMIDO/CANCELADO/EXPIRADO`. Um `RecorrenciaScheduler` (BackgroundService) varre
consentimentos vencidos e dispara cobranças, reagendando conforme periodicidade
(SEMANAL/MENSAL/ANUAL). Em produção seria job distribuído com lock; aqui single-replica.

### 8.F — PIX por Aproximação (NFC, 2025)

Token efêmero single-use com teto de valor e TTL curto (default 60s). A maquininha
apresenta o token + chave do recebedor. O token é consumido (`USADO`) **antes** de
liquidar, bloqueando replay mesmo se a liquidação demorar.

### 8.G — Open Finance fase 3

Consentimento de iniciação de pagamento por terceiro (TPP) via `id_terceiro`.
Reusa a infra de consentimento, com cobrança única (não recorrente).

## Validação

`make e2e-pix` — 8 fluxos, todos verdes:
1. Registro DICT + resolução de chave
2. Pagamento por chave + auditoria pacs.008/pacs.002 + EndToEndId no padrão
3. QR estático (valida GUI + CRC16 no payload)
4. QR dinâmico/CoBV + bloqueio de replay
5. MED com bloqueio cautelar + pacs.004 + estorno contábil
6. PIX Automático com disparo real do scheduler
7. NFC single-use com replay bloqueado
8. Open Finance iniciado por TPP

## Consequências

- ✅ PIX real fim-a-fim: DICT, ISO 20022, EMVCo, MED, Automático, NFC, Open Finance
- ✅ Topologia fiel (PSP ≠ BACEN, mensageria entre serviços)
- ✅ Auditoria das mensagens ISO 20022 no banco
- ✅ Liquidação contábil atômica reusando o modelo de movimentos existente
- ⚠ **Sem mTLS/ICP-Brasil**: a RSFN real exige certificado A1/A3. O bacen-sim
  aceita HTTP simples na rede interna do compose. Adicionar mTLS é Sprint 9.
- ⚠ **Claims DICT simplificados**: resolução imediata em vez da janela de 7 dias.
- ⚠ **Scheduler single-replica**: sem lock distribuído. Múltiplas réplicas
  exigiriam Quartz/Hangfire + advisory lock no Postgres.
- ⚠ **Sem antifraude no PIX ainda**: o fraud-detector (PyFlink) cobre
  `transferencia.solicitada`. Plugar o PIX no mesmo pipeline é evolução natural
  (publicar `pix.solicitada` no Kafka antes de liquidar).
