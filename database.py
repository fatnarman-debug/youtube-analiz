from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os
from pathlib import Path
from datetime import datetime

# Merkezi Depolama Yapılandırması (/app/storage)
# Coolify'da bu yola bir Volume Mount bağlanmalıdır (Destination: /app/storage).
# Bu klasör hem sqlite dosyasını hem de yüklenen raporları barındıracaktır.

DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_PATH = os.getenv("DATABASE_PATH")

SQLALCHEMY_DATABASE_URL = None
STORAGE_ROOT = Path("/app/storage")

# Eğer /app/storage yoksa (yerel geliştirme) yerel bir klasör kullan
if not os.path.exists("/app/storage"):
    STORAGE_ROOT = Path(__file__).resolve().parent / "storage"

# Klasörleri oluştur
REPORTS_DIR = STORAGE_ROOT / "reports"
os.makedirs(REPORTS_DIR, exist_ok=True)

if DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
elif DATABASE_PATH:
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
else:
    # Varsayılan SQLite yolu
    DB_FILE = STORAGE_ROOT / "vidinsight.db"
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"

# Kalıcılık (Persistence) Takibi
HEARTBEAT_FILE = STORAGE_ROOT / "persistence_heartbeat.txt"
IS_PREVIOUSLY_PERSISTENT = HEARTBEAT_FILE.exists()

if not IS_PREVIOUSLY_PERSISTENT:
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(f"Created at: {datetime.now()}")
    except:
        pass

# UI için durum etiketleri
if IS_PREVIOUSLY_PERSISTENT:
    STORAGE_STATUS = "KESİN KALICI ✅ (Disk Bağlı)"
else:
    STORAGE_STATUS = "İLK KURULUM / TEST ⏳ (Veriler ilk restartta kontrol edilecek)"

print(f"{'='*60}")
print(f"VERİTABANI DURUMU:")
print(f"  - Kök Dizin: {STORAGE_ROOT}")
print(f"  - URL: {SQLALCHEMY_DATABASE_URL}")
print(f"  - Durum: {STORAGE_STATUS}")
print(f"{'='*60}")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
