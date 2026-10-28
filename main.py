from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

app = FastAPI()

@app.get("/")
async def test_connection(db: Session = Depends(get_db)):
    try:
        # Run a simple query to test connection
        result = db.execute(text("SELECT 1")).scalar()
        return {"status": "success", "database_check": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
