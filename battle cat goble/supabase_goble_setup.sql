-- ============================================================
-- Battle Cats GLOBAL (Goble) — Supabase Setup SQL
-- รัน script นี้ใน Supabase SQL Editor ครั้งเดียว
-- ============================================================

-- 1. profiles_goble (เดียวกับ profiles + wallet_balance, is_admin)
CREATE TABLE IF NOT EXISTS profiles_goble (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT,
    wallet_balance  INT DEFAULT 0,
    is_admin        BOOL DEFAULT FALSE,
    loyalty_redeemed_cycles INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 2. orders_goble (เดียวกับ orders)
CREATE TABLE IF NOT EXISTS orders_goble (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    order_id            TEXT UNIQUE NOT NULL,
    username            TEXT,
    transfer_code       TEXT,
    confirmation_code   TEXT,
    country             TEXT DEFAULT 'en',
    items               JSONB,
    cat_ids             JSONB,
    amount              INT,
    payment_method      TEXT,
    status              TEXT DEFAULT 'pending',
    qr_ref              TEXT,
    retry_count         INT DEFAULT 0,
    last_retry_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ
);

-- 3. loyalty_redemptions_goble
CREATE TABLE IF NOT EXISTS loyalty_redemptions_goble (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    username    TEXT NOT NULL,
    cycles      INT NOT NULL,
    new_tc      TEXT,
    new_cc      TEXT,
    redeemed_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. code_products_goble (pre-made code shop)
CREATE TABLE IF NOT EXISTS code_products_goble (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name            TEXT NOT NULL,
    name_en         TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    description_en  TEXT DEFAULT '',
    price           INT NOT NULL,
    is_active       BOOL DEFAULT TRUE,
    image_url       TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 5. code_stock_goble
CREATE TABLE IF NOT EXISTS code_stock_goble (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    product_id          UUID REFERENCES code_products_goble(id) ON DELETE CASCADE,
    transfer_code       TEXT NOT NULL,
    confirmation_code   TEXT NOT NULL,
    inquiry_code        TEXT DEFAULT '',
    status              TEXT DEFAULT 'available',
    buyer_username      TEXT,
    order_id            TEXT,
    reserved_at         TIMESTAMPTZ,
    sold_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 6. atomic wallet deduct RPC (ป้องกัน race condition)
CREATE OR REPLACE FUNCTION deduct_wallet_atomic_goble(
    p_username TEXT,
    p_amount   INT
) RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_balance INT;
BEGIN
    SELECT wallet_balance INTO v_balance
    FROM profiles_goble
    WHERE username = p_username
    FOR UPDATE;

    IF v_balance IS NULL THEN
        RETURN jsonb_build_object('success', false, 'reason', 'user not found');
    END IF;

    IF v_balance < p_amount THEN
        RETURN jsonb_build_object('success', false, 'reason', 'insufficient_balance', 'balance', v_balance);
    END IF;

    UPDATE profiles_goble
    SET wallet_balance = wallet_balance - p_amount
    WHERE username = p_username;

    RETURN jsonb_build_object('success', true, 'new_balance', v_balance - p_amount);
END;
$$;

-- ============================================================
-- เสร็จแล้ว! ตรวจสอบ tables ที่สร้าง:
-- SELECT table_name FROM information_schema.tables
-- WHERE table_name LIKE '%_goble%';
-- ============================================================
