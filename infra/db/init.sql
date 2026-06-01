-- BankMore Case Top — schema canônico do Postgres
-- Aplicado pelo docker-entrypoint-initdb.d na primeira subida do volume.
-- IMPORTANTE: dinheiro em NUMERIC(18,2) — nunca REAL/FLOAT.

BEGIN;

-- ============================================================
-- contacorrente
-- ============================================================
CREATE TABLE IF NOT EXISTS contacorrente (
    idcontacorrente TEXT          PRIMARY KEY,
    numero          INTEGER       NOT NULL UNIQUE,
    nome            TEXT          NOT NULL,
    cpf             TEXT          NOT NULL UNIQUE,
    senha           TEXT          NOT NULL,
    salt            TEXT          NOT NULL,
    ativo           INTEGER       NOT NULL DEFAULT 1,
    criado_em       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ============================================================
-- movimento (extrato — fonte ÚNICA do saldo via SUM)
-- ============================================================
CREATE TABLE IF NOT EXISTS movimento (
    idmovimento     TEXT          PRIMARY KEY,
    idcontacorrente TEXT          NOT NULL REFERENCES contacorrente(idcontacorrente),
    numeroconta     INTEGER       NOT NULL,
    datamovimento   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    tipomovimento   CHAR(1)       NOT NULL CHECK (tipomovimento IN ('C', 'D')),
    valor           NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    -- Categoria opcional para auditoria; saldo continua sendo SUM de C - D
    categoria       TEXT          NOT NULL DEFAULT 'MOVIMENTO',
    -- Vínculo opcional a uma transferência originadora
    transferencia_id TEXT
);

CREATE INDEX IF NOT EXISTS ix_movimento_conta_data
    ON movimento (idcontacorrente, datamovimento DESC);

-- ============================================================
-- transferencia (registro auditável de cada solicitação)
-- ============================================================
CREATE TABLE IF NOT EXISTS transferencia (
    id              TEXT          PRIMARY KEY,
    correlation_id  TEXT          NOT NULL,
    cpf_origem      TEXT          NOT NULL,
    cpf_destino     TEXT          NOT NULL,
    valor           NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    tipo            TEXT          NOT NULL CHECK (tipo IN ('PIX', 'TED', 'TEF')),
    status          TEXT          NOT NULL DEFAULT 'SOLICITADA'
                       CHECK (status IN ('SOLICITADA', 'APROVADA', 'REJEITADA', 'EFETIVADA', 'COMPENSADA')),
    motivo          TEXT,
    score_fraude    NUMERIC(5,4),
    modelo_versao   TEXT,
    solicitada_em   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    decidida_em     TIMESTAMPTZ,
    efetivada_em    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_transferencia_correlation ON transferencia (correlation_id);
CREATE INDEX IF NOT EXISTS ix_transferencia_status_data ON transferencia (status, solicitada_em DESC);

-- ============================================================
-- tarifa (auditoria; valor da tarifa também é gravado como Movimento 'D' categoria=TARIFA)
-- ============================================================
CREATE TABLE IF NOT EXISTS tarifa (
    id                  TEXT          PRIMARY KEY,
    idcontacorrente     TEXT          NOT NULL REFERENCES contacorrente(idcontacorrente),
    numeroconta         INTEGER       NOT NULL,
    valor               NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    tipotransferencia   INTEGER       NOT NULL DEFAULT 0,
    dataprocessamento   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    transferencia_id    TEXT
);

CREATE INDEX IF NOT EXISTS ix_tarifa_conta ON tarifa (idcontacorrente, dataprocessamento DESC);

-- ============================================================
-- idempotencia (chave do requestId — protege replay no Worker e na API)
-- ============================================================
CREATE TABLE IF NOT EXISTS idempotencia (
    chave_idempotencia  TEXT          PRIMARY KEY,
    requisicao          TEXT,
    resultado           TEXT,
    data_processamento  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ============================================================
-- analise_fraude (escrita pelo ML Service após scoring; histórico de decisões)
-- ============================================================
CREATE TABLE IF NOT EXISTS analise_fraude (
    id                  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id      TEXT          NOT NULL,
    transferencia_id    TEXT,
    cpf_origem_hash     TEXT          NOT NULL,
    cpf_destino_hash    TEXT          NOT NULL,
    valor               NUMERIC(18,2) NOT NULL,
    tipo                TEXT          NOT NULL,
    score               NUMERIC(5,4)  NOT NULL,
    classificacao       TEXT          NOT NULL,
    regras_acionadas    TEXT[],
    modelo_versao       TEXT,
    decidido_em         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_analise_fraude_correlation ON analise_fraude (correlation_id);
CREATE INDEX IF NOT EXISTS ix_analise_fraude_data        ON analise_fraude (decidido_em DESC);

-- ============================================================
-- transferencia_outbox (Sprint 5.B — outbox pattern + Sprint 6.A — DLQ)
-- Garante atomicidade entre persistir e publicar no Kafka:
-- handler grava transferencia + outbox na mesma TX. Relay polling
-- separado publica e marca publicado_em.
--
-- Após N tentativas (default 5), o relay marca dead_letter_em — row vira
-- DLQ e para de ser reprocessada automaticamente. Ops pode listar via
-- GET /api/admin/outbox/dlq e fazer replay manual via POST /reprocess.
-- ============================================================
CREATE TABLE IF NOT EXISTS transferencia_outbox (
    id                  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    transferencia_id    TEXT          NOT NULL REFERENCES transferencia(id) ON DELETE CASCADE,
    topic               TEXT          NOT NULL,
    payload             JSONB         NOT NULL,
    criado_em           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    publicado_em        TIMESTAMPTZ,
    tentativas          INTEGER       NOT NULL DEFAULT 0,
    ultima_tentativa_em TIMESTAMPTZ,
    ultimo_erro         TEXT,
    dead_letter_em      TIMESTAMPTZ        -- Sprint 6.A: NULL = não DLQ; set = excluído do relay
);

-- Index parcial: relay só varre rows ativas (não publicadas e não-DLQ)
CREATE INDEX IF NOT EXISTS ix_outbox_pendente
    ON transferencia_outbox (criado_em)
    WHERE publicado_em IS NULL AND dead_letter_em IS NULL;

-- Index pra listar DLQ por ordem cronológica reversa (ops)
CREATE INDEX IF NOT EXISTS ix_outbox_dlq
    ON transferencia_outbox (dead_letter_em DESC)
    WHERE dead_letter_em IS NOT NULL;

-- ============================================================
-- View saldo_conta — fonte única do saldo (SUM movimentos C - D)
-- ============================================================
CREATE OR REPLACE VIEW saldo_conta AS
SELECT
    c.idcontacorrente,
    c.numero,
    c.nome,
    c.cpf,
    COALESCE(
        SUM(CASE WHEN m.tipomovimento = 'C' THEN m.valor ELSE -m.valor END),
        0
    )::NUMERIC(18,2) AS saldo
FROM contacorrente c
LEFT JOIN movimento m ON m.idcontacorrente = c.idcontacorrente
GROUP BY c.idcontacorrente;

COMMIT;
