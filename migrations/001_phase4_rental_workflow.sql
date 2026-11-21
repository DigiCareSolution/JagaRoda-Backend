-- ====================================================================
-- MIGRATION: 001_phase4_rental_workflow.sql
-- DESCRIPTION: Skema Operasional Rental Internal JagaRoda (Hardened Phase 4.1)
-- ENFORCES:
--   1. GiST Exclusion Constraint untuk Prevensi Irisan Jadwal Booking
--   2. Cross-Table Schedule Integrity: Trigger Prevensi Overlap Booking vs Maintenance dengan Row-Level Lock pada vehicles
--   3. Unique Handover Constraint (Maksimal 1 Pickup & 1 Return)
--   4. Maintenance Schedule Overlap Prevention (GiST Exclusion)
--   5. Immutable Ledger Trigger pada Tabel Payments (Anti UPDATE/DELETE)
--   6. Strict Deposit Refund Balance Guard di Level Trigger Database
--   7. Stored Procedure Atomik untuk Eksekusi Handover & Status Kendaraan dengan Batasan Privilege Ketat
--   8. Row-Level Security (RLS) Anti Akses Anonim
-- ====================================================================

-- 1. Ekstensi btree_gist untuk mendukung constraint exclusion pada tipe data kombinasi (INT & TSTZRANGE)
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- 2. TABEL SENTRAL: bookings
CREATE TABLE IF NOT EXISTS public.bookings (
    booking_id SERIAL PRIMARY KEY,
    booking_code VARCHAR(25) NOT NULL UNIQUE,
    vehicle_id INTEGER NOT NULL REFERENCES public.vehicles(vehicle_id) ON DELETE RESTRICT,
    
    -- Informasi Penyewa (Data Pelanggan Internal - Non-Account)
    customer_name VARCHAR(100) NOT NULL,
    customer_phone VARCHAR(25) NOT NULL,
    customer_id_card VARCHAR(50),      -- NIK / No. KTP / Paspor
    customer_address TEXT,
    
    -- Jadwal & Durasi
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,             -- Batas waktu pelunasan DP jika status 'Pending DP'
    rental_package VARCHAR(30) NOT NULL DEFAULT 'Lepas Kunci',
    
    -- Nilai Finansial
    daily_rate NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (daily_rate >= 0),
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (total_amount >= 0),
    deposit_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (deposit_amount >= 0),
    
    -- Status Siklus Booking
    booking_status VARCHAR(30) NOT NULL DEFAULT 'Draft'
        CHECK (booking_status IN ('Draft', 'Pending DP', 'Confirmed', 'Active', 'Completed', 'Cancelled')),
    notes TEXT,
    
    -- Audit Jejak Staf & Pembatalan
    created_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled_at TIMESTAMPTZ,
    cancelled_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    cancellation_reason TEXT,
    
    -- Validasi Integritas Jadwal
    CONSTRAINT check_dates_validity CHECK (end_date > start_date),

    -- Exclusion Constraint: Mencegah Overlap Jadwal Booking Aktif pada Armada yang Sama
    CONSTRAINT no_overlapping_active_bookings EXCLUDE USING gist (
        vehicle_id WITH =,
        tstzrange(start_date, end_date, '[)') WITH &&
    ) WHERE (booking_status IN ('Pending DP', 'Confirmed', 'Active'))
);

CREATE INDEX IF NOT EXISTS idx_bookings_vehicle ON public.bookings(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON public.bookings(booking_status);
CREATE INDEX IF NOT EXISTS idx_bookings_dates ON public.bookings(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_bookings_code ON public.bookings(booking_code);

-- 3. TABEL PERAWATAN BENGKEL: maintenance_records
-- (Didefinisikan sebelum trigger cross-table agar referensi objek valid)
CREATE TABLE IF NOT EXISTS public.maintenance_records (
    maintenance_id SERIAL PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES public.vehicles(vehicle_id) ON DELETE RESTRICT,
    damage_id INTEGER, -- Foreign key ditambahkan setelah tabel damage_reports terbuat
    maintenance_type VARCHAR(50) NOT NULL, -- e.g. 'Rutin / Ganti Oli', 'Perbaikan Insiden'
    workshop_name VARCHAR(100),
    cost NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (cost >= 0),
    start_date TIMESTAMPTZ NOT NULL,
    completion_date TIMESTAMPTZ NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'Scheduled' 
        CHECK (status IN ('Scheduled', 'In Progress', 'Completed', 'Cancelled')),
    notes TEXT,
    created_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    CONSTRAINT check_maintenance_dates CHECK (completion_date >= start_date),

    -- Mencegah Penjadwalan Servis yang Tumpang Tindih pada Unit yang Sama
    CONSTRAINT no_overlapping_maintenance EXCLUDE USING gist (
        vehicle_id WITH =,
        tstzrange(start_date, completion_date, '[)') WITH &&
    ) WHERE (status IN ('Scheduled', 'In Progress'))
);

CREATE INDEX IF NOT EXISTS idx_maintenance_vehicle ON public.maintenance_records(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_maintenance_dates ON public.maintenance_records(start_date, completion_date);
CREATE INDEX IF NOT EXISTS idx_maintenance_status ON public.maintenance_records(status);

-- ====================================================================
-- CROSS-TABLE SCHEDULE INTEGRITY TRIGGERS (BOOKING vs MAINTENANCE)
-- Menggunakan Pessimistic Row Locking pada vehicles untuk mencegah Race Condition
-- ====================================================================

-- A. Trigger pada BOOKINGS: Lock vehicle_id, lalu periksa apakah kendaraan sedang/akan diservis
CREATE OR REPLACE FUNCTION public.fn_check_booking_vs_maintenance_conflict()
RETURNS TRIGGER AS $$
DECLARE
    v_conflict_count INTEGER;
BEGIN
    -- Hanya periksa jika booking berstatus aktif yang membutuhkan alokasi unit fisik
    IF NEW.booking_status IN ('Pending DP', 'Confirmed', 'Active') THEN
        -- 1. PESSIMISTIC LOCKING DENGAN URUTAN ASCENDING (ANTI-DEADLOCK):
        -- Jika terjadi perubahan kendaraan (UPDATE vehicle_id), kunci kedua unit berurutan ASC.
        -- Jika tidak ada perubahan kendaraan, cukup kunci NEW.vehicle_id.
        IF (TG_OP = 'UPDATE') AND (OLD.vehicle_id IS DISTINCT FROM NEW.vehicle_id) THEN
            PERFORM 1 FROM public.vehicles 
            WHERE vehicle_id IN (OLD.vehicle_id, NEW.vehicle_id)
            ORDER BY vehicle_id ASC
            FOR UPDATE;
        ELSE
            PERFORM 1 FROM public.vehicles 
            WHERE vehicle_id = NEW.vehicle_id 
            FOR UPDATE;
        END IF;

        -- 2. EVALUASI JADWAL SETELAH SEMUA LOCK DIPEROLEH:
        SELECT COUNT(*)
        INTO v_conflict_count
        FROM public.maintenance_records m
        WHERE m.vehicle_id = NEW.vehicle_id
          AND m.status IN ('Scheduled', 'In Progress')
          AND tstzrange(m.start_date, m.completion_date, '[)') && tstzrange(NEW.start_date, NEW.end_date, '[)');
          
        IF v_conflict_count > 0 THEN
            RAISE EXCEPTION 'KONFLIK JADWAL ARMADA: Kendaraan (ID: %) sedang atau telah dijadwalkan dalam perawatan bengkel (maintenance) pada rentang tanggal % s/d %.',
                NEW.vehicle_id, NEW.start_date, NEW.end_date;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_booking_maintenance_conflict ON public.bookings;
CREATE TRIGGER trg_check_booking_maintenance_conflict
BEFORE INSERT OR UPDATE OF vehicle_id, start_date, end_date, booking_status ON public.bookings
FOR EACH ROW
EXECUTE FUNCTION public.fn_check_booking_vs_maintenance_conflict();

-- B. Trigger pada MAINTENANCE_RECORDS: Lock vehicle_id, lalu periksa apakah kendaraan sedang disewa
CREATE OR REPLACE FUNCTION public.fn_check_maintenance_vs_booking_conflict()
RETURNS TRIGGER AS $$
DECLARE
    v_conflict_count INTEGER;
BEGIN
    IF NEW.status IN ('Scheduled', 'In Progress') THEN
        -- 1. PESSIMISTIC LOCKING DENGAN URUTAN ASCENDING (ANTI-DEADLOCK):
        -- Hierarki kunci konsisten: selalu peroleh lock pada vehicles berurutan ASC.
        IF (TG_OP = 'UPDATE') AND (OLD.vehicle_id IS DISTINCT FROM NEW.vehicle_id) THEN
            PERFORM 1 FROM public.vehicles 
            WHERE vehicle_id IN (OLD.vehicle_id, NEW.vehicle_id)
            ORDER BY vehicle_id ASC
            FOR UPDATE;
        ELSE
            PERFORM 1 FROM public.vehicles 
            WHERE vehicle_id = NEW.vehicle_id 
            FOR UPDATE;
        END IF;

        -- 2. EVALUASI JADWAL SETELAH SEMUA LOCK DIPEROLEH:
        SELECT COUNT(*)
        INTO v_conflict_count
        FROM public.bookings b
        WHERE b.vehicle_id = NEW.vehicle_id
          AND b.booking_status IN ('Pending DP', 'Confirmed', 'Active')
          AND tstzrange(b.start_date, b.end_date, '[)') && tstzrange(NEW.start_date, NEW.completion_date, '[)');
          
        IF v_conflict_count > 0 THEN
            RAISE EXCEPTION 'KONFLIK JADWAL ARMADA: Kendaraan (ID: %) telah memiliki reservasi sewa aktif pada rentang tanggal % s/d %.',
                NEW.vehicle_id, NEW.start_date, NEW.completion_date;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_maintenance_booking_conflict ON public.maintenance_records;
CREATE TRIGGER trg_check_maintenance_booking_conflict
BEFORE INSERT OR UPDATE OF vehicle_id, start_date, completion_date, status ON public.maintenance_records
FOR EACH ROW
EXECUTE FUNCTION public.fn_check_maintenance_vs_booking_conflict();

-- 4. TABEL SERAH TERIMA: handovers (Maksimal 1 Pickup dan 1 Return per Booking)
CREATE TABLE IF NOT EXISTS public.handovers (
    handover_id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES public.bookings(booking_id) ON DELETE CASCADE,
    handover_type VARCHAR(20) NOT NULL CHECK (handover_type IN ('Pickup', 'Return')),
    odometer INTEGER NOT NULL CHECK (odometer >= 0),
    fuel_level VARCHAR(20) NOT NULL CHECK (fuel_level IN ('Empty', '1/4', '1/2', '3/4', 'Full')),
    checklist_items JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT,
    staff_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    handover_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Integritas Operasional: Maksimal 1 Pickup dan 1 Return per Booking
    CONSTRAINT unique_booking_handover_type UNIQUE (booking_id, handover_type)
);

CREATE INDEX IF NOT EXISTS idx_handovers_booking ON public.handovers(booking_id);

-- 5. TABEL IMMUTABLE LEDGER: payments
CREATE TABLE IF NOT EXISTS public.payments (
    payment_id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES public.bookings(booking_id) ON DELETE RESTRICT,
    idempotency_key VARCHAR(100) UNIQUE, -- Mencegah duplikasi submit pembayaran
    payment_type VARCHAR(30) NOT NULL CHECK (payment_type IN (
        'Down Payment', 
        'Full Payment', 
        'Deposit In', 
        'Deposit Refund', 
        'Penalty', 
        'Damage Deduction',
        'Correction Reversal'
    )),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    payment_method VARCHAR(30) NOT NULL DEFAULT 'Tunai' 
        CHECK (payment_method IN ('Tunai', 'Transfer Bank', 'EDC', 'Potong Deposit')),
    payment_status VARCHAR(20) NOT NULL DEFAULT 'Success' 
        CHECK (payment_status IN ('Success', 'Void')),
    reference_number VARCHAR(100),
    notes TEXT,
    received_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payments_booking ON public.payments(booking_id);
CREATE INDEX IF NOT EXISTS idx_payments_idempotency ON public.payments(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_payments_type ON public.payments(payment_type);

-- Trigger Immutability pada Tabel Payments (Mencegah UPDATE dan DELETE)
CREATE OR REPLACE FUNCTION public.prevent_payment_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'TABEL PAYMENTS BERSIFAT IMMUTABLE: Operasi UPDATE atau DELETE dilarang. Catat entri transaksi koreksi baru (Correction Reversal / Deposit Refund).';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_payments_immutable ON public.payments;
CREATE TRIGGER trg_payments_immutable
BEFORE UPDATE OR DELETE ON public.payments
FOR EACH ROW
EXECUTE FUNCTION public.prevent_payment_modification();

-- ====================================================================
-- DEPOSIT REFUND & OVERPAYMENT VALIDATION TRIGGER (CONCURRENCY SAFE)
-- Mencegah over-refund melalui row-level lock pada booking parent
-- ====================================================================
CREATE OR REPLACE FUNCTION public.fn_validate_payment_ledger_entry()
RETURNS TRIGGER AS $$
DECLARE
    v_total_deposit_in NUMERIC(12, 2) := 0.00;
    v_total_deposit_out NUMERIC(12, 2) := 0.00;
    v_available_deposit NUMERIC(12, 2) := 0.00;
    v_dummy_id INTEGER;
BEGIN
    -- Validasi khusus saat ada pencatatan pengembalian deposit (Deposit Refund)
    -- atau pemotongan deposit untuk ganti rugi (Damage Deduction)
    IF NEW.payment_type IN ('Deposit Refund', 'Damage Deduction') THEN
        -- RACE CONDITION GUARD: Kunci baris booking secara eksklusif (FOR UPDATE)
        -- Ini memaksa request refund konkuren untuk antre secara serial
        SELECT booking_id INTO v_dummy_id
        FROM public.bookings
        WHERE booking_id = NEW.booking_id
        FOR UPDATE;
        
        -- Hitung total deposit yang pernah masuk secara sah
        SELECT COALESCE(SUM(amount), 0.00)
        INTO v_total_deposit_in
        FROM public.payments
        WHERE booking_id = NEW.booking_id
          AND payment_type = 'Deposit In'
          AND payment_status = 'Success';
          
        -- Hitung total deposit yang sudah keluar / dipotong sebelumnya
        SELECT COALESCE(SUM(amount), 0.00)
        INTO v_total_deposit_out
        FROM public.payments
        WHERE booking_id = NEW.booking_id
          AND payment_type IN ('Deposit Refund', 'Damage Deduction')
          AND payment_status = 'Success';
          
        v_available_deposit := v_total_deposit_in - v_total_deposit_out;
        
        IF NEW.amount > v_available_deposit THEN
            RAISE EXCEPTION 'VALIDASI DEPOSIT GAGAL: Nominal pengeluaran deposit (Rp %) melebihi sisa deposit yang tersimpan (Rp %). Sisa saldo deposit saat ini: Rp %.',
                NEW.amount, v_available_deposit, v_available_deposit;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_payment_ledger ON public.payments;
CREATE TRIGGER trg_validate_payment_ledger
BEFORE INSERT ON public.payments
FOR EACH ROW
EXECUTE FUNCTION public.fn_validate_payment_ledger_entry();

-- 6. TABEL LAPORAN KERUSAKAN: damage_reports
CREATE TABLE IF NOT EXISTS public.damage_reports (
    damage_id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES public.bookings(booking_id) ON DELETE RESTRICT,
    vehicle_id INTEGER NOT NULL REFERENCES public.vehicles(vehicle_id) ON DELETE RESTRICT,
    damage_description TEXT NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'Minor' CHECK (severity IN ('Minor', 'Moderate', 'Severe')),
    repair_cost NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (repair_cost >= 0),
    photo_urls JSONB DEFAULT '[]'::jsonb,
    inspected_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_damage_booking ON public.damage_reports(booking_id);
CREATE INDEX IF NOT EXISTS idx_damage_vehicle ON public.damage_reports(vehicle_id);

-- Hubungkan FK damage_id pada maintenance_records
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_maintenance_damage'
    ) THEN
        ALTER TABLE public.maintenance_records 
        ADD CONSTRAINT fk_maintenance_damage 
        FOREIGN KEY (damage_id) REFERENCES public.damage_reports(damage_id) ON DELETE SET NULL;
    END IF;
END $$;

-- ====================================================================
-- ATOMIC HANDOVER PROCEDURE & TRANSACTION INTEGRITY
-- Menjamin atomisitas serah terima, status booking, dan status fisik unit
-- Hak akses dibatasi ketat: REVOKE FROM PUBLIC, hanya service_role / backend yang dapat mengeksekusi
-- ====================================================================
CREATE OR REPLACE FUNCTION public.execute_atomic_handover(
    p_booking_id INTEGER,
    p_handover_type VARCHAR(20),
    p_odometer INTEGER,
    p_fuel_level VARCHAR(20),
    p_checklist_items JSONB,
    p_notes TEXT,
    p_staff_id UUID,
    p_vehicle_next_status VARCHAR(20) DEFAULT NULL -- e.g. 'Available' atau 'Maintenance' saat Return
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_handover_id INTEGER;
    v_vehicle_id INTEGER;
    v_current_booking_status VARCHAR(30);
    v_target_vehicle_status VARCHAR(20);
BEGIN
    -- 1. Kunci baris booking (FOR UPDATE) untuk menjamin isolasi transaksi konkuren
    SELECT vehicle_id, booking_status
    INTO v_vehicle_id, v_current_booking_status
    FROM public.bookings
    WHERE booking_id = p_booking_id
    FOR UPDATE;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Booking ID % tidak ditemukan.', p_booking_id;
    END IF;
    
    -- Kunci juga baris kendaraan di tabel vehicles (Lock Ordering konsisten: bookings -> vehicles)
    PERFORM 1 FROM public.vehicles WHERE vehicle_id = v_vehicle_id FOR UPDATE;

    -- 2. Validasi Siklus Operasional Berdasarkan Tipe Handover
    IF p_handover_type = 'Pickup' THEN
        IF v_current_booking_status NOT IN ('Pending DP', 'Confirmed') THEN
            RAISE EXCEPTION 'Pickup Handover hanya dapat dilakukan jika booking berstatus Confirmed atau Pending DP (Status saat ini: %).', v_current_booking_status;
        END IF;
        
        -- Catat data serah terima Pickup
        INSERT INTO public.handovers (
            booking_id, handover_type, odometer, fuel_level, checklist_items, notes, staff_id, handover_time
        ) VALUES (
            p_booking_id, 'Pickup', p_odometer, p_fuel_level, COALESCE(p_checklist_items, '{}'::jsonb), p_notes, p_staff_id, now()
        ) RETURNING handover_id INTO v_handover_id;
        
        -- Update atomik: Booking menjadi Active
        UPDATE public.bookings 
        SET booking_status = 'Active', updated_by = p_staff_id, updated_at = now()
        WHERE booking_id = p_booking_id;
        
        -- Update atomik: Fisik kendaraan menjadi Rented
        UPDATE public.vehicles
        SET status = 'Rented', updated_at = now()
        WHERE vehicle_id = v_vehicle_id;
        
    ELSIF p_handover_type = 'Return' THEN
        IF v_current_booking_status != 'Active' THEN
            RAISE EXCEPTION 'Return Handover hanya dapat dilakukan pada booking yang berstatus Active (Status saat ini: %).', v_current_booking_status;
        END IF;
        
        -- Tentukan status fisik kendaraan selanjutnya (default Available, atau Maintenance jika ada insiden)
        v_target_vehicle_status := COALESCE(p_vehicle_next_status, 'Available');
        IF v_target_vehicle_status NOT IN ('Available', 'Maintenance') THEN
            RAISE EXCEPTION 'Status fisik kendaraan setelah Return harus berupa Available atau Maintenance.';
        END IF;
        
        -- Catat data serah terima Return
        INSERT INTO public.handovers (
            booking_id, handover_type, odometer, fuel_level, checklist_items, notes, staff_id, handover_time
        ) VALUES (
            p_booking_id, 'Return', p_odometer, p_fuel_level, COALESCE(p_checklist_items, '{}'::jsonb), p_notes, p_staff_id, now()
        ) RETURNING handover_id INTO v_handover_id;
        
        -- Update atomik: Booking menjadi Completed
        UPDATE public.bookings 
        SET booking_status = 'Completed', updated_by = p_staff_id, updated_at = now()
        WHERE booking_id = p_booking_id;
        
        -- Update atomik: Fisik kendaraan menjadi Available atau Maintenance
        UPDATE public.vehicles
        SET status = v_target_vehicle_status, updated_at = now()
        WHERE vehicle_id = v_vehicle_id;
        
    ELSE
        RAISE EXCEPTION 'Tipe handover tidak valid: %. Gunakan Pickup atau Return.', p_handover_type;
    END IF;

    RETURN v_handover_id;
END;
$$;

-- BATASAN PRIVILEGE EKSPLISIT:
-- 1. Cabut seluruh privilege default dari PUBLIC (mencegah akses terbuka via RPC publik)
REVOKE ALL ON FUNCTION public.execute_atomic_handover(INTEGER, VARCHAR(20), INTEGER, VARCHAR(20), JSONB, TEXT, UUID, VARCHAR(20)) FROM PUBLIC;
-- 2. Berikan izin eksekusi HANYA kepada service_role (backend FastAPI internal).
-- Role anon dan authenticated umum TIDAK memiliki akses langsung ke fungsi ini.
GRANT EXECUTE ON FUNCTION public.execute_atomic_handover(INTEGER, VARCHAR(20), INTEGER, VARCHAR(20), JSONB, TEXT, UUID, VARCHAR(20)) TO service_role;

-- 7. ROW-LEVEL SECURITY (RLS) - PERLINDUNGAN AKSES ANONIM
ALTER TABLE public.bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.handovers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.damage_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.maintenance_records ENABLE ROW LEVEL SECURITY;

-- Policy Bookings: Hanya user internal terautentikasi (Bearer JWT)
DROP POLICY IF EXISTS "Auth internal only for bookings" ON public.bookings;
CREATE POLICY "Auth internal only for bookings"
ON public.bookings FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);

-- Policy Handovers
DROP POLICY IF EXISTS "Auth internal only for handovers" ON public.handovers;
CREATE POLICY "Auth internal only for handovers"
ON public.handovers FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);

-- Policy Payments (Hanya SELECT dan INSERT, sejalan dengan trigger immutability)
DROP POLICY IF EXISTS "Auth internal select payments" ON public.payments;
CREATE POLICY "Auth internal select payments"
ON public.payments FOR SELECT
TO authenticated
USING (true);

DROP POLICY IF EXISTS "Auth internal insert payments" ON public.payments;
CREATE POLICY "Auth internal insert payments"
ON public.payments FOR INSERT
TO authenticated
WITH CHECK (true);

-- Policy Damage Reports
DROP POLICY IF EXISTS "Auth internal only for damage" ON public.damage_reports;
CREATE POLICY "Auth internal only for damage"
ON public.damage_reports FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);

-- Policy Maintenance
DROP POLICY IF EXISTS "Auth internal only for maintenance" ON public.maintenance_records;
CREATE POLICY "Auth internal only for maintenance"
ON public.maintenance_records FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);

-- 8. VIEW REKAPITULASI FINANSIAL: v_booking_financial_summary
CREATE OR REPLACE VIEW public.v_booking_financial_summary AS
SELECT 
    b.booking_id,
    b.booking_code,
    b.total_amount AS rental_billing,
    b.deposit_amount AS required_deposit,
    COALESCE(SUM(CASE WHEN p.payment_type IN ('Down Payment', 'Full Payment') AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0) AS total_rent_paid,
    COALESCE(SUM(CASE WHEN p.payment_type = 'Deposit In' AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0) AS total_deposit_received,
    COALESCE(SUM(CASE WHEN p.payment_type = 'Deposit Refund' AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0) AS total_deposit_refunded,
    COALESCE(SUM(CASE WHEN p.payment_type = 'Damage Deduction' AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0) AS total_damage_deducted,
    COALESCE(SUM(CASE WHEN p.payment_type = 'Penalty' AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0) AS total_penalties_paid,
    -- Saldo Deposit yang Masih Dipegang Perusahaan
    (
        COALESCE(SUM(CASE WHEN p.payment_type = 'Deposit In' AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0)
        - COALESCE(SUM(CASE WHEN p.payment_type = 'Deposit Refund' AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0)
        - COALESCE(SUM(CASE WHEN p.payment_type = 'Damage Deduction' AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0)
    ) AS current_deposit_held,
    -- Sisa Tagihan Sewa
    (
        b.total_amount 
        - COALESCE(SUM(CASE WHEN p.payment_type IN ('Down Payment', 'Full Payment') AND p.payment_status = 'Success' THEN p.amount ELSE 0 END), 0)
    ) AS outstanding_rent_balance
FROM public.bookings b
LEFT JOIN public.payments p ON b.booking_id = p.booking_id
GROUP BY b.booking_id, b.booking_code, b.total_amount, b.deposit_amount;
