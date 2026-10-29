from fastapi import FastAPI, Request
from supabase import create_client, Client
from workers import asgi

app = FastAPI()

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