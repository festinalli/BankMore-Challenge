-- BankMore Case Top — schema do bounded context PIX (Sprint 8)
-- Aplicado após 00-init.sql (ordem alfabética no docker-entrypoint-initdb.d).
-- Modela o PIX "de verdade": DICT, liquidação SPI/ISO 20022, MED, QR EMVCo,
-- PIX Automático e Open Finance. Dinheiro sempre NUMERIC(18,2).

BEGIN;

-- ============================================================
-- pix_chave — DICT local (chaves registradas NESTE PSP)
-- Numa instalação real, o DICT é centralizado no BACEN; aqui o bacen-sim
-- guarda o diretório global e a pix_chave é o cache/registro local.
-- ============================================================
CREATE TABLE IF NOT EXISTS pix_chave (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo            TEXT          NOT NULL CHECK (tipo IN ('CPF','CNPJ','EMAIL','TELEFONE','EVP')),
    valor_chave     TEXT          NOT NULL UNIQUE,
    idcontacorrente TEXT          NOT NULL REFERENCES contacorrente(idcontacorrente),
    ispb            TEXT          NOT NULL DEFAULT '12345678',  -- ISPB fictício do BankMore
    status          TEXT          NOT NULL DEFAULT 'ATIVA'
                       CHECK (status IN ('ATIVA','EM_PORTABILIDADE','EM_REIVINDICACAO','INATIVA')),
    criado_em       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pix_chave_conta ON pix_chave (idcontacorrente);

-- ============================================================
-- pix_pagamento — state machine de cada ordem PIX
-- EndToEndId (e2eid): formato BACEN E + ISPB(8) + YYYYMMDDHHMM + 11 chars aleatórios
-- ============================================================
CREATE TABLE IF NOT EXISTS pix_pagamento (
    id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    e2eid             TEXT          NOT NULL UNIQUE,        -- EndToEndId ISO 20022
    cpf_origem        TEXT          NOT NULL,
    chave_destino     TEXT,                                -- chave resolvida via DICT (NULL p/ manual por agência/conta)
    cpf_destino       TEXT,                                -- preenchido após resolução DICT
    ispb_destino      TEXT,
    valor             NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    tipo_iniciacao    TEXT          NOT NULL DEFAULT 'MANUAL'
                       CHECK (tipo_iniciacao IN ('MANUAL','QRCODE_ESTATICO','QRCODE_DINAMICO','NFC','AUTOMATICO','OPEN_FINANCE')),
    txid              TEXT,                                -- vínculo ao QR dinâmico/CoBV
    status            TEXT          NOT NULL DEFAULT 'INICIADO'
                       CHECK (status IN ('INICIADO','RESOLVENDO_CHAVE','LIQUIDANDO','LIQUIDADO','REJEITADO','DEVOLVIDO')),
    motivo_rejeicao   TEXT,
    pacs008_xml       TEXT,                                -- mensagem de iniciação (auditoria)
    pacs002_xml       TEXT,                                -- status report do SPI (auditoria)
    correlation_id    TEXT          NOT NULL,
    iniciado_em       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    liquidado_em      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_pix_pagamento_status   ON pix_pagamento (status, iniciado_em DESC);
CREATE INDEX IF NOT EXISTS ix_pix_pagamento_origem   ON pix_pagamento (cpf_origem, iniciado_em DESC);
CREATE INDEX IF NOT EXISTS ix_pix_pagamento_txid     ON pix_pagamento (txid) WHERE txid IS NOT NULL;

-- ============================================================
-- pix_devolucao — MED (Mecanismo Especial de Devolução)
-- ============================================================
CREATE TABLE IF NOT EXISTS pix_devolucao (
    id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    devolution_id     TEXT          NOT NULL UNIQUE,        -- RtrId ISO 20022 (D + ISPB + ...)
    pagamento_id      UUID          NOT NULL REFERENCES pix_pagamento(id),
    valor             NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    motivo            TEXT          NOT NULL                -- MD06 (fraude), BE08 (erro), etc.
                       CHECK (motivo IN ('FRAUDE','ERRO_OPERACIONAL','SOLICITACAO_CLIENTE')),
    status            TEXT          NOT NULL DEFAULT 'SOLICITADA'
                       CHECK (status IN ('SOLICITADA','BLOQUEADO','DEVOLVIDO','LIBERADO','NEGADO')),
    pacs004_xml       TEXT,
    solicitado_em     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    prazo_limite      TIMESTAMPTZ   NOT NULL,               -- SLA MED (11d golpe / 80d análise)
    resolvido_em      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_pix_devolucao_status ON pix_devolucao (status, solicitado_em DESC);

-- ============================================================
-- pix_consentimento — PIX Automático (jun/2025) + Open Finance fase 3
-- ============================================================
CREATE TABLE IF NOT EXISTS pix_consentimento (
    id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo              TEXT          NOT NULL CHECK (tipo IN ('AUTOMATICO','OPEN_FINANCE')),
    cpf_pagador       TEXT          NOT NULL,
    chave_recebedor   TEXT          NOT NULL,
    valor_fixo        NUMERIC(18,2),                        -- NULL = valor variável (até teto)
    valor_maximo      NUMERIC(18,2),                        -- teto p/ recorrência de valor variável
    periodicidade     TEXT          CHECK (periodicidade IN ('SEMANAL','MENSAL','ANUAL', NULL)),
    data_inicio       DATE,
    data_fim          DATE,
    status            TEXT          NOT NULL DEFAULT 'CRIADO'
                       CHECK (status IN ('CRIADO','AUTORIZADO','CONSUMIDO','CANCELADO','EXPIRADO','REJEITADO')),
    proxima_cobranca  TIMESTAMPTZ,                          -- agenda do scheduler (PIX Automático)
    id_terceiro       TEXT,                                 -- TPP no Open Finance
    criado_em         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    autorizado_em     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_pix_consent_agenda
    ON pix_consentimento (proxima_cobranca)
    WHERE status = 'AUTORIZADO' AND proxima_cobranca IS NOT NULL;

-- ============================================================
-- pix_qrcode — BR Codes gerados (EMVCo)
-- ============================================================
CREATE TABLE IF NOT EXISTS pix_qrcode (
    id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    txid              TEXT          NOT NULL UNIQUE,        -- 1-25 chars [A-Za-z0-9] (dinâmico exige; estático usa '***')
    tipo              TEXT          NOT NULL CHECK (tipo IN ('ESTATICO','DINAMICO','COBV')),
    chave             TEXT          NOT NULL,
    valor             NUMERIC(18,2),                        -- NULL = valor aberto (pagador define)
    payload_emv       TEXT          NOT NULL,               -- string EMVCo completa (com CRC16)
    descricao         TEXT,
    status            TEXT          NOT NULL DEFAULT 'ATIVO'
                       CHECK (status IN ('ATIVO','PAGO','EXPIRADO','CANCELADO')),
    vencimento        TIMESTAMPTZ,                          -- CoBV
    criado_em         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ============================================================
-- pix_nfc_token — tokens de aproximação (PIX por Aproximação, 2025)
-- ============================================================
CREATE TABLE IF NOT EXISTS pix_nfc_token (
    id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    token             TEXT          NOT NULL UNIQUE,        -- efêmero, single-use
    idcontacorrente   TEXT          NOT NULL REFERENCES contacorrente(idcontacorrente),
    valor_maximo      NUMERIC(18,2) NOT NULL CHECK (valor_maximo > 0),
    status            TEXT          NOT NULL DEFAULT 'ATIVO'
                       CHECK (status IN ('ATIVO','USADO','EXPIRADO')),
    expira_em         TIMESTAMPTZ   NOT NULL,
    usado_em          TIMESTAMPTZ,
    criado_em         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pix_nfc_token_lookup ON pix_nfc_token (token) WHERE status = 'ATIVO';

COMMIT;
