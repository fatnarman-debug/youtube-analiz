from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os

# Veritabanı dosya yolu kontrolü
DB_PATH = "./vidinsight.db"
if os.path.exists(DB_PATH) and os.path.isdir(DB_PATH):
    print(f"KRİTİK HATA: {DB_PATH} bir klasör olarak görünüyor! Lütfen Coolify'da 'File' veya doğru 'Volume' seçtiğinizden emin olun.")
    # Uygulamanın çökmemesi için geçici bir isim verelim ama loglarda görünsün
    DB_PATH = "./vidinsight_emergency.db"

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
