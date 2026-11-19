import os
import uuid
from typing import Any
from urllib.parse import urlparse
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Query, status, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator, AliasChoices
from supabase import create_client, Client

load_dotenv()

app = FastAPI(title="JagaRoda API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

_supabase_client: Client | None = None
_r2_client = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")

        if not supabase_url or not supabase_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SUPABASE_URL atau SUPABASE_KEY belum dikonfigurasi"
            )

        _supabase_client = create_client(supabase_url, supabase_key)

    return _supabase_client


def get_r2_bucket_name() -> str:
    return os.getenv("R2_BUCKET_NAME", "jagaroda-images")


def get_r2_client():
    global _r2_client
    if _r2_client is not None:
        return _r2_client

    r2_account_id = os.getenv("R2_ACCOUNT_ID")
    r2_access_key_id = os.getenv("R2_ACCESS_KEY_ID")
    r2_secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY")
    r2_endpoint_url = os.getenv("R2_ENDPOINT_URL")

    if not r2_endpoint_url and r2_account_id:
        r2_endpoint_url = f"https://{r2_account_id}.r2.cloudflarestorage.com"

    if not r2_endpoint_url or not r2_access_key_id or not r2_secret_access_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Konfigurasi Cloudflare R2 belum lengkap (R2_ACCOUNT_ID/R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY)"
        )

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Package boto3 belum terinstall"
        )

    _r2_client = boto3.client(
        service_name="s3",
        endpoint_url=r2_endpoint_url,
        aws_access_key_id=r2_access_key_id,
        aws_secret_access_key=r2_secret_access_key,
        region_name="auto",
        config=Config(s3={"addressing_style": "path"})
    )
    return _r2_client


def build_r2_public_url(object_key: str) -> str:
    r2_public_url = os.getenv("R2_PUBLIC_URL")
    if r2_public_url:
        return f"{r2_public_url.rstrip('/')}/{object_key.lstrip('/')}"

    r2_account_id = os.getenv("R2_ACCOUNT_ID")
    bucket_name = get_r2_bucket_name()
    if r2_account_id:
        return f"https://{bucket_name}.{r2_account_id}.r2.cloudflarestorage.com/{object_key.lstrip('/')}"

    endpoint_url = os.getenv("R2_ENDPOINT_URL", "").rstrip("/")
    return f"{endpoint_url}/{bucket_name}/{object_key.lstrip('/')}"


def extract_r2_object_key(photo_url: str) -> str:
    parsed = urlparse(photo_url)
    path = parsed.path.lstrip("/")
    bucket_name = get_r2_bucket_name()
    if path.startswith(f"{bucket_name}/"):
        return path[len(bucket_name) + 1:]
    return path


class UserLogin(BaseModel):
    email: str = Field(
        min_length=5,
        max_length=255,
        pattern=r"^[^\@\s]+@[^\@\s]+\.[^\@\s]+$",
        description="Alamat email"
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Password akun"
    )


class UserCreate(BaseModel):
    email: str = Field(
        min_length=5,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Alamat email valid"
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Password minimal 8 karakter"
    )
    username: str = Field(
        min_length=1,
        max_length=50,
        description="Username akun staf"
    )
    phone: str | None = Field(
        default=None,
        description="Nomor telepon",
        validation_alias=AliasChoices("phone", "phone_number", "no_hp")
    )

    @field_validator("username", "email", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone", mode="before")
    @classmethod
    def sanitize_phone(cls, v: Any) -> Any:
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return v


class UserRegister(BaseModel):
    email: str = Field(
        min_length=5,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Alamat email valid"
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Password minimal 8 karakter"
    )
    username: str = Field(
        min_length=1,
        max_length=50,
        description="Username akun"
    )
    phone: str | None = Field(
        default=None,
        description="Nomor telepon",
        validation_alias=AliasChoices("phone", "phone_number", "no_hp")
    )
    role: str = Field(
        default="Staff",
        description="Role akun pengguna"
    )

    @field_validator("username", "email", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone", mode="before")
    @classmethod
    def sanitize_phone(cls, v: Any) -> Any:
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        cleaned = v.strip().capitalize()
        if cleaned == "Admin":
            raise ValueError("Registrasi akun dengan role Admin tidak diizinkan")
        return cleaned


class VehicleCreate(BaseModel):
    plat_nomor: str = Field(
        min_length=3,
        max_length=20,
        description="Nomor plat kendaraan"
    )
    merk: str = Field(
        min_length=1,
        max_length=50,
        description="Merk kendaraan"
    )
    tipe: str = Field(
        min_length=1,
        max_length=50,
        description="Tipe kendaraan"
    )
    tahun: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Tahun pembuatan kendaraan"
    )
    warna: str | None = Field(
        default=None,
        max_length=30,
        description="Warna kendaraan"
    )
    nomor_stnk: str | None = Field(
        default=None,
        max_length=50,
        description="Nomor STNK kendaraan"
    )
    tarif_per_hari: float = Field(
        default=0.0,
        ge=0.0,
        description="Tarif sewa per hari"
    )
    status: str = Field(
        default="Available",
        description="Status kendaraan"
    )
    deskripsi: str | None = Field(
        default=None,
        description="Deskripsi kendaraan"
    )

    @field_validator("plat_nomor", mode="before")
    @classmethod
    def format_plat_nomor(cls, v: Any) -> Any:
        if isinstance(v, str):
            return " ".join(v.strip().upper().split())
        return v

    @field_validator("merk", "tipe", "warna", "nomor_stnk", "deskripsi", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        valid_statuses = {"Available", "Rented", "In Maintenance"}
        for s in valid_statuses:
            if s.lower() == v.strip().lower():
                return s
        raise ValueError("Status harus salah satu dari: Available, Rented, In Maintenance")


class VehicleUpdate(BaseModel):
    plat_nomor: str | None = Field(
        default=None,
        min_length=3,
        max_length=20,
        description="Nomor plat kendaraan"
    )
    merk: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Merk kendaraan"
    )
    tipe: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Tipe kendaraan"
    )
    tahun: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Tahun pembuatan kendaraan"
    )
    warna: str | None = Field(
        default=None,
        max_length=30,
        description="Warna kendaraan"
    )
    nomor_stnk: str | None = Field(
        default=None,
        max_length=50,
        description="Nomor STNK kendaraan"
    )
    tarif_per_hari: float | None = Field(
        default=None,
        ge=0.0,
        description="Tarif sewa per hari"
    )
    status: str | None = Field(
        default=None,
        description="Status kendaraan"
    )
    deskripsi: str | None = Field(
        default=None,
        description="Deskripsi kendaraan"
    )

    @field_validator("plat_nomor", mode="before")
    @classmethod
    def format_plat_nomor(cls, v: Any) -> Any:
        if isinstance(v, str):
            cleaned = " ".join(v.strip().upper().split())
            return cleaned if cleaned else None
        return v

    @field_validator("merk", "tipe", "warna", "nomor_stnk", "deskripsi", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return None
        valid_statuses = {"Available", "Rented", "In Maintenance"}
        for s in valid_statuses:
            if s.lower() == v.strip().lower():
                return s
        raise ValueError("Status harus salah satu dari: Available, Rented, In Maintenance")


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    supabase: Client = Depends(get_supabase),
) -> tuple[Client, str]:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header wajib diisi dengan format Bearer <token>"
        )

    token = credentials.credentials

    try:
        auth_response = supabase.auth.get_user(token)
        auth_user = auth_response.user
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token tidak valid atau kedaluwarsa"
        )

    if not auth_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User tidak ditemukan"
        )

    try:
        profile = (
            supabase.table("users")
            .select("role")
            .eq("user_id", str(auth_user.id))
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal memeriksa role user"
        )

    if not profile.data or profile.data[0].get("role") != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Admin yang diizinkan."
        )

    return supabase, str(auth_user.id)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    supabase: Client = Depends(get_supabase),
) -> tuple[Client, str]:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header wajib diisi dengan format Bearer <token>"
        )

    token = credentials.credentials

    try:
        auth_response = supabase.auth.get_user(token)
        auth_user = auth_response.user
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token tidak valid atau kedaluwarsa"
        )

    if not auth_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User tidak ditemukan"
        )

    return supabase, str(auth_user.id)


@app.post("/login")
async def login(
    credentials: UserLogin,
    supabase: Client = Depends(get_supabase),
):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password,
        })

        if not response or not response.user or not response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email atau password salah"
            )

        profile = (
            supabase.table("users")
            .select("user_id, username, role, phone, created_at")
            .eq("user_id", str(response.user.id))
            .limit(1)
            .execute()
        )

        return {
            "status": "success",
            "message": "Login berhasil",
            "data": {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "token_type": "bearer",
                "user": profile.data[0] if profile.data else {"user_id": str(response.user.id)}
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@app.get("/user/me")
async def get_current_user(
    auth_context: tuple[Client, str] = Depends(require_auth),
):
    supabase, user_id = auth_context

    try:
        response = (
            supabase.table("users")
            .select("user_id, username, role, phone, created_at")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profil user tidak ditemukan"
            )

        return {
            "status": "success",
            "data": response.data[0]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengambil data user: {e}"
        )


@app.get("/user")
async def get_users(
    limit: int = Query(default=50, ge=1, le=100, description="Maksimum jumlah data yang diambil"),
    offset: int = Query(default=0, ge=0, description="Offset paginasi"),
    supabase: Client = Depends(get_supabase),
):
    try:
        response = (
            supabase
            .table("users")
            .select("user_id, username, role, phone, created_at")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        return {
            "status": "success",
            "data": response.data or []
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengambil data users: {e}"
        )


@app.get("/user/{user_id}")
async def get_user_by_id(
    user_id: str,
    supabase: Client = Depends(get_supabase),
):
    try:
        response = (
            supabase
            .table("users")
            .select("user_id, username, role, phone, created_at")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        return {
            "status": "success",
            "data": response.data[0]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengambil data user: {e}"
        )


@app.post("/register", status_code=status.HTTP_201_CREATED)
@app.post("/user/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    user: UserRegister,
    supabase: Client = Depends(get_supabase),
):
    new_user_id = None

    try:
        response = supabase.auth.admin.create_user({
            "email": user.email,
            "password": user.password,
            "email_confirm": True
        })

        if not response or not response.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gagal membuat akun authentication di Supabase"
            )

        new_user_id = response.user.id

        profile_payload = {
            "user_id": str(new_user_id),
            "username": user.username,
            "role": user.role,
            "phone": user.phone
        }

        profile = (
            supabase.table("users")
            .insert(profile_payload)
            .execute()
        )

        created_data = profile.data[0] if profile.data else profile_payload

        return {
            "status": "success",
            "message": "Registrasi berhasil",
            "data": created_data
        }

    except HTTPException:
        raise

    except Exception as e:
        if supabase and new_user_id:
            try:
                supabase.auth.admin.delete_user(str(new_user_id))
            except Exception:
                pass

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@app.post("/user/add", status_code=status.HTTP_201_CREATED)
async def add_user(
    user: UserCreate,
    admin_context: tuple[Client, str] = Depends(require_admin),
):
    supabase, _ = admin_context
    new_user_id = None

    try:
        response = supabase.auth.admin.create_user({
            "email": user.email,
            "password": user.password,
            "email_confirm": True
        })

        if not response or not response.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gagal membuat akun authentication di Supabase"
            )

        new_user_id = response.user.id

        profile_payload = {
            "user_id": str(new_user_id),
            "username": user.username,
            "role": "Staff",
            "phone": user.phone
        }

        profile = (
            supabase.table("users")
            .insert(profile_payload)
            .execute()
        )

        created_data = profile.data[0] if profile.data else profile_payload

        return {
            "status": "success",
            "message": "Staff berhasil ditambahkan",
            "data": created_data
        }

    except HTTPException:
        raise

    except Exception as e:
        if supabase and new_user_id:
            try:
                supabase.auth.admin.delete_user(str(new_user_id))
            except Exception:
                pass

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@app.get("/vehicle")
@app.get("/vehicles")
async def get_vehicles(
    limit: int = Query(default=50, ge=1, le=100, description="Maksimum jumlah data yang diambil"),
    offset: int = Query(default=0, ge=0, description="Offset paginasi"),
    vehicle_status: str | None = Query(default=None, alias="status", description="Filter status kendaraan"),
    search: str | None = Query(default=None, description="Pencarian plat nomor, merk, atau tipe"),
    supabase: Client = Depends(get_supabase),
):
    try:
        query = (
            supabase
            .table("vehicles")
            .select("*, vehicle_photos(*)")
            .order("created_at", desc=True)
        )

        if vehicle_status:
            query = query.eq("status", vehicle_status)

        if search:
            search_clean = search.strip()
            query = query.or_(f"plat_nomor.ilike.%{search_clean}%,merk.ilike.%{search_clean}%,tipe.ilike.%{search_clean}%")

        response = query.range(offset, offset + limit - 1).execute()

        return {
            "status": "success",
            "data": response.data or []
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengambil data kendaraan: {e}"
        )


@app.get("/vehicle/{vehicle_id}")
@app.get("/vehicles/{vehicle_id}")
async def get_vehicle_by_id(
    vehicle_id: int,
    supabase: Client = Depends(get_supabase),
):
    try:
        response = (
            supabase
            .table("vehicles")
            .select("*, vehicle_photos(*)")
            .eq("vehicle_id", vehicle_id)
            .limit(1)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kendaraan tidak ditemukan"
            )

        return {
            "status": "success",
            "data": response.data[0]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengambil data kendaraan: {e}"
        )


@app.post("/vehicle", status_code=status.HTTP_201_CREATED)
@app.post("/vehicles", status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    vehicle: VehicleCreate,
    auth_context: tuple[Client, str] = Depends(require_auth),
):
    supabase, _ = auth_context

    try:
        payload = vehicle.model_dump()
        response = (
            supabase
            .table("vehicles")
            .insert(payload)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gagal menambahkan data kendaraan"
            )

        return {
            "status": "success",
            "message": "Kendaraan berhasil ditambahkan",
            "data": response.data[0]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@app.put("/vehicle/{vehicle_id}")
@app.put("/vehicles/{vehicle_id}")
@app.patch("/vehicle/{vehicle_id}")
@app.patch("/vehicles/{vehicle_id}")
async def update_vehicle(
    vehicle_id: int,
    vehicle: VehicleUpdate,
    auth_context: tuple[Client, str] = Depends(require_auth),
):
    supabase, _ = auth_context

    try:
        existing = (
            supabase
            .table("vehicles")
            .select("vehicle_id")
            .eq("vehicle_id", vehicle_id)
            .limit(1)
            .execute()
        )

        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kendaraan tidak ditemukan"
            )

        update_data = vehicle.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tidak ada data yang diubah"
            )

        response = (
            supabase
            .table("vehicles")
            .update(update_data)
            .eq("vehicle_id", vehicle_id)
            .execute()
        )

        return {
            "status": "success",
            "message": "Data kendaraan berhasil diperbarui",
            "data": response.data[0] if response.data else update_data
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@app.delete("/vehicle/{vehicle_id}")
@app.delete("/vehicles/{vehicle_id}")
async def delete_vehicle(
    vehicle_id: int,
    auth_context: tuple[Client, str] = Depends(require_auth),
):
    supabase, _ = auth_context

    try:
        existing = (
            supabase
            .table("vehicles")
            .select("vehicle_id")
            .eq("vehicle_id", vehicle_id)
            .limit(1)
            .execute()
        )

        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kendaraan tidak ditemukan"
            )

        photos_response = (
            supabase
            .table("vehicle_photos")
            .select("photo_url")
            .eq("vehicle_id", vehicle_id)
            .execute()
        )

        if photos_response.data:
            try:
                s3 = get_r2_client()
                bucket_name = get_r2_bucket_name()
                for p in photos_response.data:
                    url = p.get("photo_url")
                    if url:
                        key = extract_r2_object_key(url)
                        s3.delete_object(Bucket=bucket_name, Key=key)
            except Exception:
                pass

        supabase.table("vehicles").delete().eq("vehicle_id", vehicle_id).execute()

        return {
            "status": "success",
            "message": "Kendaraan berhasil dihapus"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menghapus kendaraan: {e}"
        )


@app.post("/vehicle/{vehicle_id}/photos", status_code=status.HTTP_201_CREATED)
@app.post("/vehicles/{vehicle_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_vehicle_photo(
    vehicle_id: int,
    file: UploadFile = File(..., description="File gambar kendaraan"),
    photo_type: str = Form(default="Other", description="Tipe foto (Exterior, Interior, Other)"),
    auth_context: tuple[Client, str] = Depends(require_auth),
):
    supabase, _ = auth_context

    valid_types = {"Exterior", "Interior", "Other"}
    matched_type = None
    for t in valid_types:
        if t.lower() == photo_type.strip().lower():
            matched_type = t
            break

    if not matched_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="photo_type harus salah satu dari: Exterior, Interior, Other"
        )

    existing = (
        supabase
        .table("vehicles")
        .select("vehicle_id")
        .eq("vehicle_id", vehicle_id)
        .limit(1)
        .execute()
    )

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kendaraan tidak ditemukan"
        )

    content_type = file.content_type or ""
    filename_orig = file.filename or ""
    ext = os.path.splitext(filename_orig)[1].lower()
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}

    if not content_type.startswith("image/") and ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File harus berupa gambar (JPEG, PNG, WEBP, GIF, HEIC)"
        )

    if ext not in allowed_exts:
        ext = ".jpg"

    s3 = get_r2_client()
    bucket_name = get_r2_bucket_name()
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    object_key = f"vehicles/{vehicle_id}/{unique_filename}"

    try:
        s3.upload_fileobj(
            file.file,
            bucket_name,
            object_key,
            ExtraArgs={"ContentType": content_type if content_type.startswith("image/") else "image/jpeg"}
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengunggah foto ke Cloudflare R2: {e}"
        )

    photo_url = build_r2_public_url(object_key)

    try:
        insert_response = (
            supabase
            .table("vehicle_photos")
            .insert({
                "vehicle_id": vehicle_id,
                "photo_url": photo_url,
                "photo_type": matched_type
            })
            .execute()
        )

        created_data = insert_response.data[0] if insert_response.data else {
            "vehicle_id": vehicle_id,
            "photo_url": photo_url,
            "photo_type": matched_type
        }

        return {
            "status": "success",
            "message": "Foto kendaraan berhasil diunggah",
            "data": created_data
        }

    except Exception as e:
        try:
            s3.delete_object(Bucket=bucket_name, Key=object_key)
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gagal menyimpan data foto kendaraan: {e}"
        )


@app.delete("/vehicle/{vehicle_id}/photos/{photo_id}")
@app.delete("/vehicles/{vehicle_id}/photos/{photo_id}")
async def delete_vehicle_photo(
    vehicle_id: int,
    photo_id: int,
    auth_context: tuple[Client, str] = Depends(require_auth),
):
    supabase, _ = auth_context

    photo_response = (
        supabase
        .table("vehicle_photos")
        .select("photo_id, photo_url")
        .eq("vehicle_id", vehicle_id)
        .eq("photo_id", photo_id)
        .limit(1)
        .execute()
    )

    if not photo_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Foto kendaraan tidak ditemukan"
        )

    photo_data = photo_response.data[0]
    photo_url = photo_data.get("photo_url")

    if photo_url:
        try:
            s3 = get_r2_client()
            bucket_name = get_r2_bucket_name()
            object_key = extract_r2_object_key(photo_url)
            s3.delete_object(Bucket=bucket_name, Key=object_key)
        except Exception:
            pass

    supabase.table("vehicle_photos").delete().eq("photo_id", photo_id).execute()

    return {
        "status": "success",
        "message": "Foto kendaraan berhasil dihapus"
    }


@app.get("/")
def root():
    return {"status": "ok", "service": "jaga-roda-backend"}


@app.get("/count")
async def count_numbers():
    angka1 = 5
    angka2 = 10
    return {"hasil": angka1 + angka2}


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }


@app.get("/health/supabase")
async def supabase_health(
    supabase: Client = Depends(get_supabase)
):
    try:
        supabase.table("users").select("user_id").limit(1).execute()

        return {
            "status": "healthy",
            "database": "connected"
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase connection failed: {str(e)}"
        )
