-- =============================================================================
-- Migration: 001_notifications_and_telegram.sql
-- Project: JagaRoda Backend
-- Description: Creates persistent notifications, telegram accounts, and linking tokens tables
-- =============================================================================

-- 1. Notifications Table
CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    type VARCHAR(50) NOT NULL DEFAULT 'info',
    related_entity_type VARCHAR(50) NULL,
    related_entity_id VARCHAR(100) NULL,
    action_url TEXT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    read_at TIMESTAMPTZ NULL
);

-- Foreign Key to users table (if users table exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_notifications_user') THEN
            ALTER TABLE public.notifications
            ADD CONSTRAINT fk_notifications_user
            FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;
        END IF;
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        NULL;
END $$;

-- Indexes for efficient querying & pagination
CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON public.notifications (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_is_read ON public.notifications (user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON public.notifications (type);


-- 2. Telegram Linked Accounts Table
CREATE TABLE IF NOT EXISTS public.telegram_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE,
    telegram_chat_id BIGINT NOT NULL UNIQUE,
    telegram_username VARCHAR(255) NULL,
    first_name VARCHAR(255) NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    preferences JSONB NOT NULL DEFAULT '{"vehicle_updates": true, "account_updates": true, "system_alerts": true}'::jsonb,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Foreign Key to users table
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_telegram_accounts_user') THEN
            ALTER TABLE public.telegram_accounts
            ADD CONSTRAINT fk_telegram_accounts_user
            FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;
        END IF;
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        NULL;
END $$;

-- Indexes for Telegram accounts
CREATE INDEX IF NOT EXISTS idx_telegram_accounts_user_id ON public.telegram_accounts (user_id);
CREATE INDEX IF NOT EXISTS idx_telegram_accounts_chat_id ON public.telegram_accounts (telegram_chat_id);


-- 3. Telegram Temporary Linking Tokens Table
CREATE TABLE IF NOT EXISTS public.telegram_linking_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash VARCHAR(64) NOT NULL UNIQUE, -- SHA-256 hex digest
    user_id UUID NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    is_used BOOLEAN NOT NULL DEFAULT FALSE,
    used_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Foreign Key to users table
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_telegram_tokens_user') THEN
            ALTER TABLE public.telegram_linking_tokens
            ADD CONSTRAINT fk_telegram_tokens_user
            FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;
        END IF;
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        NULL;
END $$;

-- Indexes for token validation & cleanup
CREATE INDEX IF NOT EXISTS idx_linking_tokens_hash ON public.telegram_linking_tokens (token_hash);
CREATE INDEX IF NOT EXISTS idx_linking_tokens_user_id ON public.telegram_linking_tokens (user_id);
CREATE INDEX IF NOT EXISTS idx_linking_tokens_expires_at ON public.telegram_linking_tokens (expires_at);


-- 4. Row Level Security (RLS) Configuration
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.telegram_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.telegram_linking_tokens ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    -- Notifications Policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can view their own notifications') THEN
        CREATE POLICY "Users can view their own notifications" ON public.notifications
        FOR SELECT USING (auth.uid() = user_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can update their own notifications') THEN
        CREATE POLICY "Users can update their own notifications" ON public.notifications
        FOR UPDATE USING (auth.uid() = user_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role has full access to notifications') THEN
        CREATE POLICY "Service role has full access to notifications" ON public.notifications
        FOR ALL USING (auth.role() = 'service_role');
    END IF;

    -- Telegram Accounts Policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can view their own telegram account') THEN
        CREATE POLICY "Users can view their own telegram account" ON public.telegram_accounts
        FOR SELECT USING (auth.uid() = user_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role has full access to telegram_accounts') THEN
        CREATE POLICY "Service role has full access to telegram_accounts" ON public.telegram_accounts
        FOR ALL USING (auth.role() = 'service_role');
    END IF;

    -- Telegram Linking Tokens Policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role has full access to telegram_tokens') THEN
        CREATE POLICY "Service role has full access to telegram_tokens" ON public.telegram_linking_tokens
        FOR ALL USING (auth.role() = 'service_role');
    END IF;
END $$;
