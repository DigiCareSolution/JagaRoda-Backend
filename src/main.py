from typing import Any
from fastapi import FastAPI, Request, Depends, Query, status, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
from supabase import create_client, Client
from workers import asgi

app = FastAPI(title="JagaRoda API", version="0.1.0")

security = HTTPBearer(auto_error=False)

_supabase_client_cache: dict[tuple[str, str], Client] = {}


def get_supabase(request: Request) -> Client:
    env = request.scope.get("env")
    if env is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Environment variables tidak ditemukan pada worker scope"
        )

    supabase_url = getattr(env, "SUPABASE_URL", None) or (env.get("SUPABASE_URL") if hasattr(env, "get") else None)
    supabase_key = getattr(env, "SUPABASE_KEY", None) or (env.get("SUPABASE_KEY") if hasattr(env, "get") else None)

    if not supabase_url or not supabase_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_URL atau SUPABASE_KEY belum dikonfigurasi"
        )

    cache_key = (str(supabase_url), str(supabase_key))
    if cache_key not in _supabase_client_cache:
        _supabase_client_cache[cache_key] = create_client(str(supabase_url), str(supabase_key))

    return _supabase_client_cache[cache_key]


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

    @field_validator("username", "email", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


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
            .select("user_id, username, role, created_at")
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
            .select("user_id, username, role, created_at")
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

        profile = (
            supabase.table("users")
            .insert({
                "user_id": str(new_user_id),
                "username": user.username,
                "role": "Staff"
            })
            .execute()
        )

        created_data = profile.data[0] if profile.data else {
            "user_id": str(new_user_id),
            "username": user.username,
            "role": "Staff"
        }

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
async def test_connection(supabase: Client = Depends(get_supabase)):
    try:
        try:
            supabase.table("dummy_test_table").select("*").limit(1).execute()
        except Exception as db_error:
            error_message = str(db_error)

            if "PGRST205" in error_message:
                return {
                    "status": "success",
                    "message": "Connected to Supabase successfully! API keys and URL are working perfectly."
                }
            raise db_error

        return {"status": "success"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/count")
async def count_numbers():
    angka1 = 5
    angka2 = 10
    return {"hasil": angka1 + angka2}


Default = asgi.entrypoint(app)
