-- Migration: Add financial, booking, deposit, refund, maintenance tables
-- Safe migration: adds new tables, constraints, indexes, triggers without altering existing tables.

-- 1. ENUM types
CREATE TYPE payment_status AS ENUM ('pending', 'completed', 'failed');
CREATE TYPE booking_status AS ENUM ('pending_dp', 'confirmed', 'in_use', 'completed', 'cancelled');
CREATE TYPE transaction_type AS ENUM ('payment', 'refund', 'deposit', 'deposit_refund');

-- 2. Payments (immutable ledger)
CREATE TABLE payments (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id) ON DELETE RESTRICT,
    amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    status payment_status NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    external_ref TEXT UNIQUE,  -- idempotency key from payment provider
    CONSTRAINT payments_immutable_chk CHECK (status IN ('pending','completed','failed'))
);

-- Prevent UPDATE/DELETE on payments (immutability)
CREATE OR REPLACE FUNCTION prevent_payment_modification()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Payments are immutable; use a new transaction for corrections.' USING ERRCODE = 'P0001';
    RETURN NULL; -- never reached
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_payments_no_update BEFORE UPDATE OR DELETE ON payments
FOR EACH ROW EXECUTE FUNCTION prevent_payment_modification();

-- 3. Refunds (stored as separate rows in payments with type = 'refund')
-- Instead of a separate table, we use payments with transaction_type = 'refund'.
-- Add column transaction_type to payments.
ALTER TABLE payments ADD COLUMN transaction_type transaction_type NOT NULL DEFAULT 'payment';

-- Ensure refund rows reference original payment via original_payment_id (optional)
ALTER TABLE payments ADD COLUMN original_payment_id BIGINT REFERENCES payments(id) ON DELETE RESTRICT;

-- 4. Deposits and Deposit Refunds (also using payments table)
-- Deposits are stored with transaction_type = 'deposit'
-- Deposit refunds use transaction_type = 'deposit_refund' and reference original deposit.

-- 5. Bookings
CREATE TABLE bookings (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id) ON DELETE RESTRICT,
    status booking_status NOT NULL DEFAULT 'pending_dp',
    start_datetime TIMESTAMPTZ NOT NULL,
    end_datetime TIMESTAMPTZ NOT NULL,
    total_amount NUMERIC(12,2) NOT NULL CHECK (total_amount >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,  -- expires for pending DP bookings
    CONSTRAINT chk_booking_times CHECK (end_datetime > start_datetime)
);

CREATE INDEX idx_bookings_vehicle_time ON bookings (vehicle_id, start_datetime, end_datetime);

-- 6. Booking status transition trigger (enforce valid transitions)
CREATE OR REPLACE FUNCTION validate_booking_status_transition()
RETURNS trigger AS $$
DECLARE
    allowed BOOLEAN;
BEGIN
    allowed := FALSE;
    IF TG_OP = 'INSERT' THEN
        allowed := NEW.status = 'pending_dp';
    ELSIF TG_OP = 'UPDATE' THEN
        CASE OLD.status
            WHEN 'pending_dp' THEN
                allowed := NEW.status IN ('confirmed', 'cancelled');
            WHEN 'confirmed' THEN
                allowed := NEW.status IN ('in_use', 'cancelled');
            WHEN 'in_use' THEN
                allowed := NEW.status IN ('completed', 'cancelled');
            WHEN 'completed' THEN
                allowed := FALSE; -- terminal state
            WHEN 'cancelled' THEN
                allowed := FALSE; -- terminal state
            ELSE
                allowed := FALSE;
        END CASE;
    END IF;
    IF NOT allowed THEN
        RAISE EXCEPTION 'Invalid booking status transition from % to %', OLD.status, NEW.status USING ERRCODE = 'P0002';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_booking_status BEFORE INSERT OR UPDATE ON bookings
FOR EACH ROW EXECUTE FUNCTION validate_booking_status_transition();

-- 7. Maintenance schedule
CREATE TABLE maintenance_schedules (
    id BIGSERIAL PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id) ON DELETE RESTRICT,
    start_datetime TIMESTAMPTZ NOT NULL,
    end_datetime TIMESTAMPTZ NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maintenance_times CHECK (end_datetime > start_datetime)
);

CREATE INDEX idx_maintenance_vehicle_time ON maintenance_schedules (vehicle_id, start_datetime, end_datetime);

-- 8. RLS policies (example placeholders, to be enabled per role)
-- Enable row level security on sensitive tables
ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;

-- Example policy: users can see only their own bookings/payments
CREATE POLICY user_bookings_policy ON bookings
    USING (user_id = auth.uid());
CREATE POLICY user_payments_policy ON payments
    USING (user_id = auth.uid());

-- 9. Idempotency for payments: unique external_ref already defined.

-- 10. Additional indexes for fast lookup
CREATE INDEX idx_payments_user ON payments (user_id);
CREATE INDEX idx_payments_vehicle ON payments (vehicle_id);

-- End of migration
