from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routers import custom_foods, diary, favorites, foods, meals, users, weights

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="MacroPal's own API. Firebase Auth for identity, PostgreSQL for everything else.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

for router in (foods, users, diary, meals, custom_foods, weights, favorites):
    app.include_router(router.router)


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "online",
        "version": app.version,
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        return {"status": "degraded", "database": "unavailable", "detail": str(exc)}

    return {"status": "ok", "database": "ok"}
