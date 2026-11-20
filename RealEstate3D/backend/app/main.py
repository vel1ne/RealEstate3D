from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.api.routers.admin_property_filters import (
    router as admin_property_filters_router,
)
from app.api.routers.admin_property_types import router as admin_property_types_router
from app.api.routers.properties import router as properties_router
from app.api.routers.property_types import router as property_types_router
from app.db.session import engine

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
    admin_property_types_router,
    prefix="/api/v1",
)
app.include_router(
    property_types_router,
    prefix="/api/v1",
)
app.include_router(
    admin_property_filters_router,
    prefix="/api/v1",
)
app.include_router(properties_router, prefix="/api/v1")