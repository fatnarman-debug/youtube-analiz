from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os
from pathlib import Path

# Absolute path for the database file
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vidinsight.db"

# Veritabanı dosya yolu kontrolü
if DB_PATH.exists() and DB_PATH.is_dir():
    print(f"KRİTİK HATA: {DB_PATH} bir klasör olarak görünüyor! Acil durum veri tabanı oluşturuluyor.")
    DB_PATH = BASE_DIR / "vidinsight_emergency.db"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

print(f"Bağlanılan Veritabanı Yolu: {SQLALCHEMY_DATABASE_URL}")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
