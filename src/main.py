from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel, Field
from supabase import create_client, Client
from workers import asgi

app = FastAPI()

def get_supabase(request: Request) -> Client:
    env = request.scope["env"]

    supabase_url = env.SUPABASE_URL
    supabase_key = env.SUPABASE_KEY

    return create_client(supabase_url, supabase_key)

class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    username: str = Field(min_length=1, max_length=50)

def require_admin(request: Request, authorization: str | None):
    # Pastikan header Authorization tersedia
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header wajib diisi"
        )

    # Pastikan format Bearer Token benar
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="Format token tidak valid"
        )

    supabase = get_supabase(request)

    # Verifikasi Access Token melalui Supabase Auth
    try:
        auth_response = supabase.auth.get_user(token)
        auth_user = auth_response.user
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Access token tidak valid atau kedaluwarsa"
        )

    if not auth_user:
        raise HTTPException(
            status_code=401,
            detail="User tidak ditemukan"
        )

    # Periksa role user di public.users
    try:
        profile = (
            supabase.table("users")
            .select("role")
            .eq("user_id", str(auth_user.id))
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Gagal memeriksa role user"
        )

    if not profile.data or profile.data[0]["role"] != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Akses ditolak. Hanya Admin yang diizinkan."
        )

    return supabase, auth_user.id

@app.get("/user")
async def get_users(request: Request):
    try:
        supabase = get_supabase(request)

        response = (
            supabase
            .table("users")
            .select("user_id, username, role, created_at")
            .execute()
        )

        return {
            "status": "success",
            "data": response.data
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/user/{user_id}")
async def get_user_by_id(user_id: str, request: Request):
    try:
        supabase = get_supabase(request)

        response = (
            supabase
            .table("users")
            .select("user_id, username, role, created_at")
            .eq("user_id", user_id)
            .execute()
        )

        if not response.data:
            return {
                "status": "error",
                "message": "User not found"
            }

        return {
            "status": "success",
            "data": response.data[0]
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/")
async def test_connection(request: Request):
    try:
        env = request.scope["env"]
        supabase_url = env.SUPABASE_URL
        supabase_key = env.SUPABASE_KEY
        
        supabase: Client = create_client(supabase_url, supabase_key)
        
        try:
            # Intentionally query a fake table to trigger a response from Supabase
            supabase.table("dummy_test_table").select("*").limit(1).execute()
        except Exception as db_error:
            error_message = str(db_error)
            
            # Catch the specific Supabase PostgREST error that means "table not found"
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

@app.post("/user/add")
async def add_user(
    user: UserCreate,
    request: Request,
    authorization: str | None = Header(default=None)
):
    supabase = None
    new_user_id = None

    try:
        # Pastikan yang mengakses adalah Admin
        supabase, admin_id = require_admin(request, authorization)

        # Buat akun baru di Supabase Authentication
        response = supabase.auth.admin.create_user({
            "email": user.email,
            "password": user.password,
            "email_confirm": True
        })

        new_user_id = response.user.id

        # Masukkan profil ke public.users
        profile = (
            supabase.table("users")
            .insert({
                "user_id": str(new_user_id),
                "username": user.username,
                "role": "Staff"
            })
            .execute()
        )

        return {
            "status": "success",
            "message": "Staff berhasil ditambahkan",
            "data": profile.data[0]
        }

    except HTTPException:
        raise

    except Exception as e:
        # Jika profil gagal dibuat, hapus akun Auth agar tidak yatim
        if supabase and new_user_id:
            try:
                supabase.auth.admin.delete_user(str(new_user_id))
            except Exception:
                pass

        raise HTTPException(
            status_code=400,
            detail=str(e)
        )