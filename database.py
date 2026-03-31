from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os
from pathlib import Path

# Production'da kalıcı storage için /data klasörü kullan.
# Docker volume ile bu klasör host makinede saklanır ve Redeploy'da SİLİNMEZ.
# Eğer /data klasörü yoksa (yerel geliştirme ortamı), proje klasörünü kullan.
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
LOCAL_FALLBACK = Path(__file__).resolve().parent

if DATA_DIR.exists() and DATA_DIR.is_dir():
    DB_PATH = DATA_DIR / "vidinsight.db"
    print(f"Üretim Modu: Kalıcı veritabanı yolu -> {DB_PATH}")
else:
    DB_PATH = LOCAL_FALLBACK / "vidinsight.db"
    print(f"Geliştirme Modu: Yerel veritabanı yolu -> {DB_PATH}")

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

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
