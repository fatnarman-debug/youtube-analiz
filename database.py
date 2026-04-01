from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os
from pathlib import Path

# Veritabanı dosyası her zaman /app/vidinsight.db konumunda tutulur.
# Coolify'da bu yola bir Volume Mount bağlıdır (Destination: /app/vidinsight.db).
# Bu sayede Redeploy yapıldığında Docker container yenilense bile
# veritabanı dosyası sunucuda kalıcı olarak korunur, kullanıcılar silinmez.
# Veritabanı yapılandırması
# Öncelik Sırası:
# 1. DATABASE_URL (env) - Örn: sqlite:////data/vidinsight.db
# 2. DATABASE_PATH (env) - Örn: /data/vidinsight.db
# 3. /data dizini varsa (/data/vidinsight.db)
# 4. Mevcut dizin (vidinsight.db)

DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_PATH = os.getenv("DATABASE_PATH")

if DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    STORAGE_TYPE = "Sistem Değişkeni (URL - Dış Kaynak)"
elif DATABASE_PATH:
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
    STORAGE_TYPE = "Sistem Değişkeni (PATH - Dış Kaynak)"
elif os.path.exists("/data"):
    # /data klasörü varsa (Volume bağlanmışsa) orayı kullanırız.
    DB_PATH = Path("/data/vidinsight.db")
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
    STORAGE_TYPE = "Otomatik Dış Birim (/data - KALICI)"
else:
    # Yerel geliştirme ortamı
    BASE_DIR = Path(__file__).resolve().parent
    DB_PATH = BASE_DIR / "vidinsight.db"
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
    STORAGE_TYPE = "Yerel Klasör (YALNIZCA GELİŞTİRME - GÖÇEBE)"

# Veritabanı dosyasının olduğu klasörün varlığından emin olalım.
# SQLite bir dosyaya yazacağı zaman klasörü otomatik oluşturmaz, bu yüzden bir hata alabiliriz.
db_file_path = None
if SQLALCHEMY_DATABASE_URL.startswith("sqlite:///"):
    path_str = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")
    db_file_path = Path(path_str)
    # Üst klasörü (örneğin /data) oluştur
    os.makedirs(db_file_path.parent, exist_ok=True)

print(f"{'='*50}")
print(f"VERİTABANI YAPILANDIRMASI:")
print(f"  - Depolama Tipi: {STORAGE_TYPE}")
print(f"  - URL: {SQLALCHEMY_DATABASE_URL}")
if db_file_path:
    print(f"  - Dosya Mevcut mu: {'Evet' if db_file_path.exists() else 'Hayır (Yeni oluşturulacak)'}")
print(f"{'='*50}")

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
