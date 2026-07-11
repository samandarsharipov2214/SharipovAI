BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS project_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT UNIQUE,
    username TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin','service')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key TEXT NOT NULL DEFAULT 'SharipovAI',
    external_chat_id TEXT,
    title TEXT,
    created_by UUID REFERENCES project_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_key, external_chat_id)
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user','assistant','system','tool','service')),
    actor_id TEXT,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS project_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key TEXT NOT NULL DEFAULT 'SharipovAI',
    namespace TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    value JSONB NOT NULL,
    source_conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    source_message_id UUID REFERENCES conversation_messages(id) ON DELETE SET NULL,
    confidence NUMERIC(5,2) NOT NULL DEFAULT 100 CHECK (confidence >= 0 AND confidence <= 100),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_key, namespace, memory_key)
);

CREATE TABLE IF NOT EXISTS ai_organ_state (
    organ_key TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('starting','healthy','degraded','blocked','offline')),
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_heartbeat_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS market_quotes (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    symbol TEXT NOT NULL,
    category TEXT NOT NULL,
    bid NUMERIC,
    ask NUMERIC,
    last_price NUMERIC NOT NULL CHECK (last_price > 0),
    exchange_timestamp_ms BIGINT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (provider, symbol, category, exchange_timestamp_ms)
);

CREATE TABLE IF NOT EXISTS news_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    source_event_id TEXT,
    headline TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbols TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    assessment JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source, source_event_id)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    environment TEXT NOT NULL CHECK (environment IN ('paper','testnet','mainnet')),
    account_key TEXT NOT NULL,
    equity NUMERIC NOT NULL,
    available_balance NUMERIC NOT NULL,
    positions JSONB NOT NULL DEFAULT '[]'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (environment, account_key, captured_at)
);

CREATE TABLE IF NOT EXISTS trading_candidates (
    candidate_id TEXT PRIMARY KEY,
    environment TEXT NOT NULL CHECK (environment IN ('paper','testnet','mainnet')),
    symbol TEXT NOT NULL,
    category TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('Buy','Sell')),
    decision TEXT NOT NULL CHECK (decision IN ('ALLOW','BLOCK')),
    payload JSONB NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CHECK (expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS execution_journal (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id TEXT NOT NULL REFERENCES trading_candidates(candidate_id) ON DELETE RESTRICT,
    environment TEXT NOT NULL CHECK (environment IN ('paper','testnet','mainnet')),
    order_link_id TEXT NOT NULL UNIQUE,
    order_id TEXT UNIQUE,
    symbol TEXT NOT NULL,
    category TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('Buy','Sell')),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL,
    cum_exec_qty NUMERIC NOT NULL DEFAULT 0 CHECK (cum_exec_qty >= 0),
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS private_order_state (
    order_link_id TEXT PRIMARY KEY,
    order_id TEXT UNIQUE,
    environment TEXT NOT NULL CHECK (environment IN ('testnet','mainnet')),
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('Buy','Sell')),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL,
    cum_exec_qty NUMERIC NOT NULL DEFAULT 0 CHECK (cum_exec_qty >= 0),
    avg_price NUMERIC,
    exchange_updated_at_ms BIGINT NOT NULL,
    raw_event JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','error','critical')),
    actor TEXT,
    correlation_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON conversation_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_namespace_updated ON project_memory(project_key, namespace, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_symbol_received ON market_quotes(symbol, category, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_events(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_portfolio_environment_time ON portfolio_snapshots(environment, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_environment_created ON trading_candidates(environment, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_candidate ON execution_journal(candidate_id);
CREATE INDEX IF NOT EXISTS idx_execution_status_updated ON execution_journal(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);

INSERT INTO schema_migrations(version)
VALUES ('0001_unified_core')
ON CONFLICT (version) DO NOTHING;

COMMIT;
