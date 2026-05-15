from app.db.session import Base, engine
from app import models  # noqa: F401
from app.services.importer import ensure_schema
from app.db.session import SessionLocal


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_schema(db)
        db.commit()
    print("Database tables created.")
