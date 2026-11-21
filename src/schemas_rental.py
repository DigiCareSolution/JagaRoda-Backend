import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


class BookingStatus(str, Enum):
    DRAFT = "Draft"
    PENDING_DP = "Pending DP"
    CONFIRMED = "Confirmed"
    ACTIVE = "Active"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class HandoverType(str, Enum):
    PICKUP = "Pickup"
    RETURN = "Return"


class FuelLevel(str, Enum):
    EMPTY = "Empty"
    ONE_QUARTER = "1/4"
    HALF = "1/2"
    THREE_QUARTERS = "3/4"
    FULL = "Full"


class VehicleOperationalStatus(str, Enum):
    AVAILABLE = "Available"
    RENTED = "Rented"
    MAINTENANCE = "Maintenance"


class PaymentType(str, Enum):
    DOWN_PAYMENT = "Down Payment"
    FULL_PAYMENT = "Full Payment"
    DEPOSIT_IN = "Deposit In"
    DEPOSIT_REFUND = "Deposit Refund"
    PENALTY = "Penalty"
    DAMAGE_DEDUCTION = "Damage Deduction"
    CORRECTION_REVERSAL = "Correction Reversal"


class PaymentMethod(str, Enum):
    CASH = "Tunai"
    BANK_TRANSFER = "Transfer Bank"
    EDC = "EDC"
    DEPOSIT_DEDUCTION = "Potong Deposit"


class DamageSeverity(str, Enum):
    MINOR = "Minor"
    MODERATE = "Moderate"
    SEVERE = "Severe"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


# =====================================================================
# ATURAN TRANSISI STATUS BOOKING (FINITE STATE MACHINE)
# =====================================================================
VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    BookingStatus.DRAFT.value: {
        BookingStatus.PENDING_DP.value,
        BookingStatus.CONFIRMED.value,
        BookingStatus.CANCELLED.value,
    },
    BookingStatus.PENDING_DP.value: {
        BookingStatus.CONFIRMED.value,
        BookingStatus.CANCELLED.value,
    },
    BookingStatus.CONFIRMED.value: {
        BookingStatus.ACTIVE.value,       # Hanya dapat dipicu oleh aksi Pickup Handover atomik
        BookingStatus.CANCELLED.value,    # Pembatalan sebelum unit diserahkan
    },
    BookingStatus.ACTIVE.value: {
        BookingStatus.COMPLETED.value,    # Hanya dapat dipicu oleh Return Handover & penyelesaian finansial
    },
    BookingStatus.COMPLETED.value: set(), # Terminal state (tidak dapat diubah)
    BookingStatus.CANCELLED.value: set(), # Terminal state (tidak dapat diubah)
}


def validate_booking_transition(current_status: str, target_status: str) -> None:
    """Memvalidasi apakah transisi dari current_status ke target_status diperbolehkan."""
    if current_status == target_status:
        return
    allowed = VALID_STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ValueError(
            f"Transisi status booking dari '{current_status}' ke '{target_status}' tidak diizinkan. "
            f"Transisi yang valid: {', '.join(allowed) if allowed else 'Tidak ada (Status Terminal)'}"
        )


# =====================================================================
# PYDANTIC SCHEMAS: BOOKINGS
# =====================================================================
class BookingCreate(BaseModel):
    vehicle_id: int = Field(..., description="ID kendaraan inventaris perusahaan")
    customer_name: str = Field(..., min_length=2, max_length=100, description="Nama lengkap penyewa")
    customer_phone: str = Field(..., min_length=8, max_length=25, description="Nomor telepon penyewa")
    customer_id_card: str | None = Field(default=None, max_length=50, description="NIK/No. KTP/Paspor")
    customer_address: str | None = Field(default=None, description="Alamat domisili penyewa")
    
    start_date: datetime = Field(..., description="Waktu mulai sewa")
    end_date: datetime = Field(..., description="Waktu selesai sewa")
    expires_at: datetime | None = Field(default=None, description="Batas waktu setoran DP (untuk status Pending DP)")
    rental_package: str = Field(default="Lepas Kunci", max_length=30)
    
    daily_rate: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"), description="Tarif sewa per hari")
    total_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"), description="Total biaya sewa keseluruhan")
    deposit_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"), description="Nilai uang jaminan (deposit)")
    
    booking_status: BookingStatus = Field(default=BookingStatus.DRAFT, description="Status awal booking")
    notes: str | None = Field(default=None, description="Catatan perjalanan/tujuan sewa")

    @field_validator("customer_name", "customer_phone", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def validate_dates_and_status(self):
        if self.end_date <= self.start_date:
            raise ValueError("Tanggal selesai sewa (end_date) harus lebih besar dari tanggal mulai sewa (start_date)")
        
        # Validasi otomatis expires_at untuk Pending DP
        if self.booking_status == BookingStatus.PENDING_DP and not self.expires_at:
            self.expires_at = self.start_date
        return self


class BookingStatusUpdate(BaseModel):
    target_status: BookingStatus = Field(..., description="Status baru yang dituju")


class BookingCancelRequest(BaseModel):
    cancellation_reason: str = Field(..., min_length=3, max_length=500, description="Alasan pembatalan reservasi")


# =====================================================================
# PYDANTIC SCHEMAS: HANDOVERS (DENGAN SINKRONISASI STATUS KENDARAAN)
# =====================================================================
class HandoverCreate(BaseModel):
    handover_type: HandoverType = Field(..., description="Tipe serah terima: Pickup atau Return")
    odometer: int = Field(..., ge=0, description="Angka kilometer speedometer kendaraan")
    fuel_level: FuelLevel = Field(..., description="Tingkat bahan bakar tangki kendaraan")
    checklist_items: dict[str, Any] = Field(default_factory=dict, description="Checklist fisik bodi, ban, surat, alat")
    notes: str | None = Field(default=None, description="Catatan temuan fisik")
    handover_time: datetime | None = Field(default=None, description="Waktu pelaksanaan handover")
    
    # Menentukan status armada pasca-handover (Khusus Return: Available atau Maintenance)
    vehicle_next_status: VehicleOperationalStatus | None = Field(
        default=None, 
        description="Target status fisik kendaraan pasca-return (Available / Maintenance). Abaikan saat Pickup."
    )

    @model_validator(mode="after")
    def validate_handover_vehicle_status(self):
        if self.handover_type == HandoverType.RETURN:
            if self.vehicle_next_status and self.vehicle_next_status not in (VehicleOperationalStatus.AVAILABLE, VehicleOperationalStatus.MAINTENANCE):
                raise ValueError("Status kendaraan setelah Return hanya boleh 'Available' atau 'Maintenance'")
        return self


# =====================================================================
# PYDANTIC SCHEMAS: PAYMENTS (IMMUTABLE LEDGER & REFUND VALIDATION)
# =====================================================================
def generate_default_idempotency_key() -> str:
    """Helper untuk menghasilkan idempotency key acak yang unik."""
    return f"pay-{uuid.uuid4().hex}"


class PaymentCreate(BaseModel):
    idempotency_key: str = Field(
        default_factory=generate_default_idempotency_key, 
        min_length=5,
        max_length=100, 
        description="Kunci idempoten unik untuk mencegah duplikasi submit pembayaran"
    )
    payment_type: PaymentType = Field(..., description="Jenis mutasi pembayaran / deposit")
    amount: Decimal = Field(..., gt=Decimal("0.00"), description="Nominal transaksi (harus lebih besar dari 0)")
    payment_method: PaymentMethod = Field(default=PaymentMethod.CASH, description="Metode transaksi")
    reference_number: str | None = Field(default=None, max_length=100, description="Nomor referensi bank / kwitansi")
    notes: str | None = Field(default=None, description="Keterangan transaksi")

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def handle_explicit_idempotency_key(cls, v: Any) -> str:
        # Jika klien mengirimkan None atau string kosong eksplisit, fallback ke key acak baru
        if v is None or (isinstance(v, str) and not v.strip()):
            return generate_default_idempotency_key()
        return str(v).strip()


class DepositRefundValidation(BaseModel):
    """Schema bantuan untuk memvalidasi ketersediaan saldo deposit sebelum eksekusi refund."""
    booking_id: int
    requested_refund_amount: Decimal = Field(..., gt=Decimal("0.00"))
    current_deposit_held: Decimal = Field(..., ge=Decimal("0.00"))

    @model_validator(mode="after")
    def validate_refund_ceiling(self):
        if self.requested_refund_amount > self.current_deposit_held:
            raise ValueError(
                f"Nominal refund (Rp {self.requested_refund_amount:,.2f}) tidak boleh melebihi sisa deposit "
                f"yang tersimpan (Rp {self.current_deposit_held:,.2f})"
            )
        return self


# =====================================================================
# PYDANTIC SCHEMAS: DAMAGE & MAINTENANCE
# =====================================================================
class DamageReportCreate(BaseModel):
    damage_description: str = Field(..., min_length=5, description="Deskripsi rinci kerusakan unit")
    severity: DamageSeverity = Field(default=DamageSeverity.MINOR, description="Tingkat keparahan kerusakan")
    repair_cost: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"), description="Estimasi biaya perbaikan")
    photo_urls: list[str] = Field(default_factory=list, description="Daftar URL foto bukti kerusakan di R2")


class MaintenanceCreate(BaseModel):
    vehicle_id: int = Field(..., description="ID kendaraan yang diservis")
    damage_id: int | None = Field(default=None, description="Referensi laporan kerusakan jika terkait insiden")
    maintenance_type: str = Field(..., min_length=3, max_length=50, description="Tipe perawatan (Rutin/Ganti Oli/Perbaikan)")
    workshop_name: str | None = Field(default=None, max_length=100, description="Nama bengkel rekanan")
    cost: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"), description="Estimasi biaya servis")
    start_date: datetime = Field(..., description="Waktu mulai pengerjaan servis")
    completion_date: datetime = Field(..., description="Estimasi waktu selesai servis")
    notes: str | None = Field(default=None, description="Catatan pengerjaan")

    @model_validator(mode="after")
    def validate_maintenance_dates(self):
        if self.completion_date < self.start_date:
            raise ValueError("Tanggal selesai servis (completion_date) tidak boleh lebih awal dari tanggal mulai (start_date)")
        return self


# =====================================================================
# PYDANTIC SCHEMAS: RESPONSE SERIALIZERS
# =====================================================================
class BookingResponse(BaseModel):
    booking_id: int
    booking_code: str
    vehicle_id: int
    customer_name: str
    customer_phone: str
    customer_id_card: str | None = None
    customer_address: str | None = None
    start_date: datetime
    end_date: datetime
    expires_at: datetime | None = None
    rental_package: str
    daily_rate: Decimal
    total_amount: Decimal
    deposit_amount: Decimal
    booking_status: str
    notes: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_by: str | None = None
    updated_at: datetime
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None
    cancellation_reason: str | None = None

    class Config:
        from_attributes = True


class HandoverResponse(BaseModel):
    handover_id: int
    booking_id: int
    handover_type: str
    odometer: int
    fuel_level: str
    checklist_items: dict[str, Any]
    notes: str | None = None
    staff_id: str | None = None
    handover_time: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentResponse(BaseModel):
    payment_id: int
    booking_id: int
    idempotency_key: str | None = None
    payment_type: str
    amount: Decimal
    payment_method: str
    payment_status: str
    reference_number: str | None = None
    notes: str | None = None
    received_by: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class FinancialSummaryResponse(BaseModel):
    booking_id: int
    booking_code: str
    rental_billing: Decimal
    required_deposit: Decimal
    total_rent_paid: Decimal
    total_deposit_received: Decimal
    total_deposit_refunded: Decimal
    total_damage_deducted: Decimal
    total_penalties_paid: Decimal
    current_deposit_held: Decimal
    outstanding_rent_balance: Decimal
    is_financially_settled: bool

    class Config:
        from_attributes = True
