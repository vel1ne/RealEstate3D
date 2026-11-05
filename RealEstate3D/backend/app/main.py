from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.db.session import engine
from app.api.routers.property_types import router as property_types_router

app = FastAPI(title="RealEstate3D API", version="1.0.0")


@app.get("/")
async def root():
    return {"message": "RealEstate3D API"}


@app.get("/health/db")
def check_database():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {"database": "connected"}

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed",
        ) from exc


app.include_router(
    property_types_router,
    prefix="/api/v1",
)