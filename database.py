from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os
from pathlib import Path

# Veritabanı dosyası her zaman /app/vidinsight.db konumunda tutulur.
# Coolify'da bu yola bir Volume Mount bağlıdır (Destination: /app/vidinsight.db).
# Bu sayede Redeploy yapıldığında Docker container yenilense bile
# veritabanı dosyası sunucuda kalıcı olarak korunur, kullanıcılar silinmez.
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vidinsight.db"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

print(f"Veritabanı Yolu: {SQLALCHEMY_DATABASE_URL}")

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
