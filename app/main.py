from fastapi import FastAPI
from app.api.routes import router
from app.db.session import SessionLocal
from app.services.importer import ensure_schema

app = FastAPI(title="Cinema Showtime API", version="0.1.0")
app.include_router(router, prefix="/api")


@app.on_event("startup")
def sync_schema():
    with SessionLocal() as db:
        ensure_schema(db)
        db.commit()


@app.get("/health")
def health():
    return {"status": "ok"}
