from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path
from datetime import datetime

# ============================================================
# VidInsight v1.0.8 - Temiz Veritabani Yapilandirmasi
# ============================================================
print("[VidInsight v1.0.8] Veritabani yapilandirmasi basliyor...")

# Yazilabilir bir dizin bul
# Oncelik: /app/storage (Coolify volume) > ./storage (lokal) > /tmp (son care)
STORAGE_ROOT = None
for candidate in ["/app/storage", os.path.join(os.getcwd(), "storage"), "/tmp"]:
    try:
        os.makedirs(candidate, exist_ok=True)
        test_path = os.path.join(candidate, ".write_test")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        STORAGE_ROOT = candidate
        print(f"[v1.0.8] Yazilabilir dizin bulundu: {candidate}")
        break
    except Exception as e:
        print(f"[v1.0.8] Dizin yazilabilir degil: {candidate} ({e})")
        continue

if not STORAGE_ROOT:
    STORAGE_ROOT = "/tmp"
    print("[v1.0.8] UYARI: /tmp son care olarak kullaniliyor!")

# Raporlar dizini
REPORTS_DIR = Path(STORAGE_ROOT) / "reports"
os.makedirs(REPORTS_DIR, exist_ok=True)

# Veritabani URL'si
# DIKKAT: Bu ismi asla degistirmeyin, aksi takdirde veriler sifirlanir!
DB_FILE = os.path.join(STORAGE_ROOT, "vidinsight_saas.db")
DATABASE_URL = f"sqlite:///{DB_FILE}"
SQLALCHEMY_DATABASE_URL = DATABASE_URL

print(f"[v1.0.8] Veritabani dosyasi: {DB_FILE}")

# SQLAlchemy Engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Kalicilik takibi
HEARTBEAT_FILE = os.path.join(STORAGE_ROOT, "heartbeat.txt")
IS_PREVIOUSLY_PERSISTENT = os.path.exists(HEARTBEAT_FILE)
STORAGE_STATUS = "KALICI (Disk Bagli)" if IS_PREVIOUSLY_PERSISTENT else "ILK KURULUM"

try:
    with open(HEARTBEAT_FILE, "w") as f:
        f.write(f"v1.0.8 - {datetime.now()}")
except:
    pass

print(f"[v1.0.8] Depolama durumu: {STORAGE_STATUS}")
print(f"[v1.0.8] Veritabani yapilandirmasi tamamlandi.")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
