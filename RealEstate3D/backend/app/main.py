from fastapi import FastAPI

from app.api.routers.properties import router as properties_router


app = FastAPI(
    title="Commercial Property API",
    description="API для подбора коммерческой недвижимости",
    version="0.1.0",
)

app.include_router(
    properties_router,
    prefix="/api/v1",
)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Commercial Property API"}
