from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os
from pathlib import Path

# Veritabanı dosyası her zaman /app/vidinsight.db konumunda tutulur.
# Coolify'da bu yola bir Volume Mount bağlıdır (Destination: /app/vidinsight.db).
# Bu sayede Redeploy yapıldığında Docker container yenilense bile
# veritabanı dosyası sunucuda kalıcı olarak korunur, kullanıcılar silinmez.
# Veritabanı Yapılandırması
# Öncelik Sırası:
# 1. DATABASE_URL (env) - Örn: sqlite:////data/vidinsight.db
# 2. DATABASE_PATH (env) - Örn: /data/vidinsight.db
# 3. /data dizini varsa (/data/vidinsight.db)
# 4. Mevcut dizin (vidinsight.db)

DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_PATH = os.getenv("DATABASE_PATH")

SQLALCHEMY_DATABASE_URL = None
STORAGE_TYPE = "Bilinmiyor"
IS_PERSISTENT = False

if DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    STORAGE_TYPE = "Sistem Değişkeni (URL - KALICI)"
    IS_PERSISTENT = True
elif DATABASE_PATH:
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
    STORAGE_TYPE = "Sistem Değişkeni (PATH - KALICI)"
    IS_PERSISTENT = True
elif os.path.exists("/data"):
    # /data klasörü varsa (Volume bağlanmışsa) orayı kullanırız.
    DB_PATH = Path("/data/vidinsight.db")
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
    STORAGE_TYPE = "Otomatik Dış Birim (/data - KALICI)"
    IS_PERSISTENT = True
else:
    # Yerel geliştirme ortamı
    BASE_DIR = Path(__file__).resolve().parent
    DB_PATH = BASE_DIR / "vidinsight.db"
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
    STORAGE_TYPE = "Yerel Klasör (YALNIZCA GELİŞTİRME - GÖÇEBE)"
    IS_PERSISTENT = False

# Veritabanı yolunu çıkar
db_file_path = None
if SQLALCHEMY_DATABASE_URL.startswith("sqlite:///"):
    path_str = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")
    db_file_path = Path(path_str)
    # Üst klasörü (örneğin /data) oluştur (Sadece yetki varsa)
    try:
        os.makedirs(db_file_path.parent, exist_ok=True)
    except:
        pass

# Kalıcılık (Persistence) Takibi
# Bu kısım, sunucu her başladığında bir dosya oluşturur / kontrol eder.
# Eğer dosya bir önceki açılıştan kalmışsa STORAGE_TYPE "KESİN KALICI ✅" olur.
HEARTBEAT_FILE = None
IS_PREVIOUSLY_PERSISTENT = False
if db_file_path:
    HEARTBEAT_FILE = db_file_path.parent / "persistence_heartbeat.txt"
    if HEARTBEAT_FILE.exists():
        IS_PREVIOUSLY_PERSISTENT = True
    else:
        try:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(f"Created at: {datetime.now()}")
        except:
            pass

# Nihai karar (UI için)
if IS_PREVIOUSLY_PERSISTENT:
    STORAGE_TYPE = STORAGE_TYPE.replace("KALICI", "KESİN KALICI ✅")
else:
    STORAGE_TYPE = STORAGE_TYPE.replace("KALICI", "İLK KURULUM / TEST ⏳")

actual_mount = IS_PREVIOUSLY_PERSISTENT # UI için bunu kullanalım

print(f"{'='*60}")
print(f"VERİTABANI DURUMU:")
print(f"  - Depolama Tipi: {STORAGE_TYPE}")
print(f"  - URL: {SQLALCHEMY_DATABASE_URL}")
print(f"  - Kalıcılık Testi: {'BAŞARILI (Dosya bulundu)' if actual_mount else 'İLK AÇILIŞ (Dosya oluşturuldu)'}")
if db_file_path:
    size = 0
    if db_file_path.exists(): size = os.path.getsize(db_file_path) / 1024
    print(f"  - Dosya Boyutu: {size:.2f} KB")
print(f"{'='*60}")

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
