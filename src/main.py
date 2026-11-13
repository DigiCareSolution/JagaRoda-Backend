import os
from typing import Any
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Query, status, HTTPException
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
