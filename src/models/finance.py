from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, validator, PositiveFloat, condecimal

class PaymentStatus(str, Enum):
    pending = 'pending'
    completed = 'completed'
    failed = 'failed'

class TransactionType(str, Enum):
    payment = 'payment'
    refund = 'refund'
    deposit = 'deposit'
    deposit_refund = 'deposit_refund'

class Payment(BaseModel):
    id: Optional[int] = None
    user_id: str = Field(..., description='UUID of the user')
    vehicle_id: int = Field(..., description='Vehicle identifier')
    amount: condecimal(gt=0, max_digits=12, decimal_places=2)
    status: PaymentStatus = PaymentStatus.pending
    transaction_type: TransactionType = TransactionType.payment
    external_ref: Optional[str] = None  # Idempotency key from payment provider
    created_at: Optional[datetime] = None
    original_payment_id: Optional[int] = None

    @validator('external_ref')
    def strip_external_ref(cls, v):
        return v.strip() if isinstance(v, str) else v

class BookingStatus(str, Enum):
    pending_dp = 'pending_dp'
    confirmed = 'confirmed'
    in_use = 'in_use'
    completed = 'completed'
    cancelled = 'cancelled'

class Booking(BaseModel):
    id: Optional[int] = None
    user_id: str = Field(..., description='UUID of the renter')
    vehicle_id: int = Field(..., description='Vehicle identifier')
    status: BookingStatus = BookingStatus.pending_dp
    start_datetime: datetime
    end_datetime: datetime
    total_amount: condecimal(ge=0, max_digits=12, decimal_places=2)
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    @validator('end_datetime')
    def check_time_order(cls, v, values):
        start = values.get('start_datetime')
        if start and v <= start:
            raise ValueError('end_datetime must be after start_datetime')
        return v

class MaintenanceSchedule(BaseModel):
    id: Optional[int] = None
    vehicle_id: int = Field(..., description='Vehicle identifier')
    start_datetime: datetime
    end_datetime: datetime
    description: Optional[str] = None
    created_at: Optional[datetime] = None

    @validator('end_datetime')
    def check_time_order(cls, v, values):
        start = values.get('start_datetime')
        if start and v <= start:
            raise ValueError('end_datetime must be after start_datetime')
        return v
