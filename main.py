from fastapi import FastAPI, Depends, Request, Form, Response, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import os
import shutil
import models
import traceback
from database import engine, get_db, SessionLocal, STORAGE_STATUS, STORAGE_ROOT, REPORTS_DIR, DATABASE_URL
from auth import get_password_hash, verify_password, create_access_token, decode_access_token
import datetime
import stripe
from fastapi import BackgroundTasks
from email.message import EmailMessage
import aiosmtplib
from dotenv import load_dotenv
import json
from functools import lru_cache

load_dotenv() # .env dosyasını yükle

# Stripe Configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_51K...yazdırmayalım_simdi") # Buraya gerçek secret key gelmeli
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_9kskzuBvWaIY8Kkr3VsnFNZKpfy4RKuN")
stripe.api_key = STRIPE_SECRET_KEY

# Absolute paths for Docker stability
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# --- ZIRHLI BASLATMA VE KURULUM ---
try:
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Admin 'hadibaslayalim' (Turkce karakter icermez)
    admin_exists = db.query(models.User).filter(models.User.username == "hadibaslayalim").first()
    if not admin_exists:
        new_admin = models.User(
            username="hadibaslayalim",
            email="admin@vid-insight.com",
            full_name="Admin User",
            password_hash=get_password_hash("12345678qw.ASX"),
            credits=999999,
            subscription_plan="agency"
        )
        db.add(new_admin)
        db.commit()
    db.close()
    print("Sistem basariyla hazirlandi.")
except Exception as e:
    print(f"Sistem baslatma hatasi (Gozardi edildi): {e}")

# Stripe Configuration with extra safety
try:
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_9kskzuBvWaIY8Kkr3VsnFNZKpfy4RKuN")
    stripe.api_key = STRIPE_SECRET_KEY
    print("Stripe yapılandırması yüklendi.")
except Exception as e:
    print(f"!!! STRIPE YAPILANDIRMA HATASI: {e}")

app = FastAPI()

@lru_cache()
def load_translations():
    locales_dir = os.path.join(BASE_DIR, "locales")
    langs = {}
    if os.path.exists(locales_dir):
        for f in os.listdir(locales_dir):
            if f.endswith(".json"):
                lang_code = f.replace(".json", "")
                with open(os.path.join(locales_dir, f), "r", encoding="utf-8") as file:
                    langs[lang_code] = json.load(file)
    return langs

def get_locale(request: Request):
    lang = request.query_params.get("lang")
    if lang in ["tr", "en", "es", "de"]:
        return lang
    lang_cookie = request.cookies.get("locale")
    if lang_cookie in ["tr", "en", "es", "de"]:
        return lang_cookie
    return "tr"

def t(request: Request, key: str):
    lang = get_locale(request)
    translations = load_translations()
    return translations.get(lang, {}).get(key, translations.get("tr", {}).get(key, key))

@app.middleware("http")
async def lang_middleware(request: Request, call_next):
    lang = request.query_params.get("lang")
    response = await call_next(request)
    if lang in ["tr", "en", "es", "de"]:
        response.set_cookie(key="locale", value=lang, max_age=31536000)
    return response

# --- SMTP CONFIG ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "VidInsight <noreply@vid-insight.com>")

async def send_report_email(user_email: str, user_name: str, video_title: str):
    """Kullanıcıya raporunun hazır olduğunu bildiren şık bir HTML e-posta gönderir."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("!!! SMTP ayarları eksik, e-posta gönderilemedi.")
        return

    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = user_email
    message["Subject"] = f"✨ Raporunuz Hazır: {video_title}"

    html_content = f"""
    <html>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden;">
                <div style="background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%); padding: 30px; text-align: center; color: white;">
                    <h1 style="margin: 0; font-size: 24px;">VidInsight</h1>
                    <p style="margin: 5px 0 0 0; opacity: 0.9;">Analiziniz Tamamlandı!</p>
                </div>
                <div style="padding: 30px; background: #ffffff;">
                    <p>Merhaba <strong>{user_name}</strong>,</p>
                    <p>Beklediğiniz <strong>"{video_title}"</strong> videonuzun analizi başarıyla tamamlandı ve raporunuz panelinize yüklendi.</p>
                    <div style="margin: 30px 0; text-align: center;">
                        <a href="https://vid-insight.com/dashboard" style="background: #6366f1; color: white; padding: 12px 30px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block;">
                            Raporu Görüntüle & İndir
                        </a>
                    </div>
                    <p style="font-size: 0.9rem; color: #64748b;">
                        Herhangi bir sorunuz olursa admin@vid-insight.com üzerinden bizimle iletişime geçebilirsiniz.
                    </p>
                </div>
                <div style="background: #f8fafc; padding: 20px; text-align: center; font-size: 0.8rem; color: #94a3b8; border-top: 1px solid #e2e8f0;">
                    © 2026 VidInsight. Tüm hakları saklıdır.
                </div>
            </div>
        </body>
    </html>
    """
    message.set_content("Raporunuz hazır! Detaylar için panelinizi kontrol edin.")
    message.add_alternative(html_content, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            use_tls=False,
            start_tls=True
        )
        print(f"--- E-posta gönderildi: {user_email}")
    except Exception as e:
        print(f"!!! E-posta gönderim hatası: {e}")

async def send_welcome_email(user_email: str, user_name: str):
    """Yeni üyelere hoş geldin e-postası gönderir."""
    if not SMTP_USER or not SMTP_PASSWORD: return

    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = user_email
    message["Subject"] = "Welcome to VidInsight! 🚀"

    html_content = f"""
    <html>
        <body style="font-family: sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 10px; overflow: hidden;">
                <div style="background: #0F172A; padding: 20px; text-align: center; color: white;">
                    <h1>VidInsight</h1>
                </div>
                <div style="padding: 30px;">
                    <h2>Daha Akıllı Video Analizine Hoş Geldiniz!</h2>
                    <p>Merhaba <strong>{user_name}</strong>,</p>
                    <p>VidInsight ailesine katıldığınız için mutluyuz. Artık binlerce yorumu saniyeler içinde analiz edebilir, kitlenizi daha iyi tanıyabilirsiniz.</p>
                    <p>Hemen başlamak için ilk video linkinizi dashboard'unuza ekleyin!</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="https://vid-insight.com/dashboard" style="background: #F59E0B; color: #000; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold;">Hemen Başla</a>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """
    message.set_content("VidInsight'a Hoş Geldiniz! Hemen başlayın.")
    message.add_alternative(html_content, subtype="html")
    try:
        await aiosmtplib.send(message, hostname=SMTP_HOST, port=SMTP_PORT, username=SMTP_USER, password=SMTP_PASSWORD, use_tls=False, start_tls=True)
        print(f"--- Hoş geldin e-postası gönderildi: {user_email}")
    except: pass

async def send_analysis_received_email(user_email: str, user_name: str, video_url: str):
    """Analiz talebi alındığında kullanıcıya onay e-postası gönderir."""
    if not SMTP_USER or not SMTP_PASSWORD: return

    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = user_email
    message["Subject"] = "Videonuzu Aldık! 📽️"

    html_content = f"""
    <html>
        <body style="font-family: sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 10px; overflow: hidden;">
                <div style="background: #0F172A; padding: 20px; text-align: center; color: white;">
                    <h1>VidInsight</h1>
                </div>
                <div style="padding: 30px;">
                    <p>Merhaba <strong>{user_name}</strong>,</p>
                    <p><strong>{video_url}</strong> adresli videonuz için analiz talebiniz başarıyla alındı.</p>
                    <p>Ekibimiz (veya yapay zekamız) şu an yorumları tarıyor. Analiz tamamlandığında size tekrar haber vereceğiz.</p>
                    <p>Güncel durumu panelinizden takip edebilirsiniz.</p>
                </div>
            </div>
        </body>
    </html>
    """
    message.set_content("Videonuzu aldık, analiz başlıyor!")
    message.add_alternative(html_content, subtype="html")
    try:
        await aiosmtplib.send(message, hostname=SMTP_HOST, port=SMTP_PORT, username=SMTP_USER, password=SMTP_PASSWORD, use_tls=False, start_tls=True)
    except: pass

# --- v1.0.8 DEBUG ROTASI ---
@app.get("/debug")
async def debug_system():
    return {
        "versiyon": "v1.0.8",
        "durum": "aktif",
        "veritabani": DATABASE_URL,
        "storage": STORAGE_ROOT,
        "yazma_izni": os.access(STORAGE_ROOT, os.W_OK) if os.path.exists(STORAGE_ROOT) else False
    }

# --- GLOBAL HATA YAKALAYICI ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_detail = traceback.format_exc()
    print(f"!!! GLOBAL HATA: {error_detail}")
    return JSONResponse(
        status_code=500,
        content={"hata": str(exc), "traceback": error_detail, "v": "1.0.8"}
    )

# Setup Templates and Static Files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if TEMPLATES_DIR.exists():
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.globals["t"] = t
    templates.env.globals["get_locale"] = get_locale
else:
    templates = None

# Hardcoded Admin
ADMIN_CREDENTIALS = {
    "username": "hadibaslayalim",
    "password": "12345678qw.ASX"
}
ADMIN_SESSION_NAME = "vidinsight_admin_session"
USER_SESSION_NAME = "vidinsight_user_session"

# --- UTILS ---
def get_current_user(request: Request, db: Session):
    token = request.cookies.get(USER_SESSION_NAME)
    if not token: return None
    payload = decode_access_token(token)
    if not payload: return None
    username = payload.get("sub")
    user = db.query(models.User).filter(models.User.username == username).first()
    if user and not user.is_active:
        return None
    return user

def check_and_renew_credits(user: models.User, db: Session):
    """Aylık kredi yenileme ve sıfırlama mantığı (Lazy Renewal)"""
    if user.subscription_plan == "free":
        return

    now = datetime.datetime.utcnow()
    # Eğer yenileme tarihi yoksa (eski kullanıcı), bugünü ata ve çık
    if not user.last_renewal_date:
        user.last_renewal_date = now
        db.commit()
        return

    # Eğer son yenilemeden beri 30 gün geçmişse
    if (now - user.last_renewal_date).days >= 30:
        # Planlara göre kredi sıfırla ve yeni hak tanımla
        plan_credits = {
            "creator": 5,
            "agency": 10,
            "single": 0 # Single paketler aylık yenilenmez
        }
        
        if user.subscription_plan in plan_credits:
            new_credits = plan_credits[user.subscription_plan]
            # Sadece aylık planlar (creator, agency) için yenileme yap
            if new_credits > 0:
                user.credits = new_credits
                user.last_renewal_date = now
                db.commit()

# --- PUBLIC ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"user": user}
    )

@app.get("/giris", response_class=HTMLResponse)
async def user_login_get(request: Request, error: str = None, success: bool = False):
    return templates.TemplateResponse(request=request, name="user_login.html", context={"error": error, "success": success})

@app.post("/giris")
async def user_login_post(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    # Email VEYA Username ile giriş
    user = db.query(models.User).filter((models.User.email == email) | (models.User.username == email)).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request=request, name="user_login.html", context={"error": "Geçersiz bilgiler."})
    
    if not user.is_active:
        return templates.TemplateResponse(request=request, name="user_login.html", context={"error": "Hesabınız yönetici tarafından pasife alınmıştır."})
    
    token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key=USER_SESSION_NAME, value=token, httponly=True)
    return response

@app.get("/kayit", response_class=HTMLResponse)
async def signup_get(request: Request, error: str = None):
    return templates.TemplateResponse(request=request, name="signup.html", context={"error": error})

@app.post("/kayit")
async def signup_post(request: Request, 
                      background_tasks: BackgroundTasks,
                      username: str = Form(...),
                      email: str = Form(...),
                      full_name: str = Form(...),
                      password: str = Form(...),
                      db: Session = Depends(get_db)
):
    try:
        # Check if username or email exists
        user_exists = db.query(models.User).filter(
            (models.User.username == username) | (models.User.email == email)
        ).first()
        
        if user_exists:
            return templates.TemplateResponse(request=request, name="user_signup.html", context={
                "request": request, "error": "Bu kullanıcı adı veya e-posta zaten kullanımda."
            })

        new_user = models.User(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=get_password_hash(password)
        )
        new_user.credits = 1
        new_user.subscription_plan = "free"
        new_user.last_renewal_date = datetime.datetime.utcnow()

        db.add(new_user)
        db.commit()

        # Kayıt sonrası HOŞ GELDİN e-postası
        background_tasks.add_task(send_welcome_email, email, full_name)

        return RedirectResponse(url="/giris?msg=success", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        err_msg = traceback.format_exc()
        return JSONResponse(status_code=500, content={"error": str(e), "traceback": err_msg})

@app.get("/cikis")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie(USER_SESSION_NAME)
    return response

# --- USER ROUTES ---
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/giris", status_code=status.HTTP_303_SEE_OTHER)
    
    analyses = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.user_id == user.id).order_by(models.AnalysisRequest.id.desc()).all()
    
    # Kredileri kontrol et ve yenile
    check_and_renew_credits(user, db)
    
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"user": user, "analyses": analyses})

@app.post("/analyze")
async def create_analysis(request: Request, 
                          background_tasks: BackgroundTasks,
                          video_url: str = Form(...), 
                          db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/giris", status_code=status.HTTP_303_SEE_OTHER)
    
    if user.credits <= 0:
        # Dashboard'a hata mesajıyla dön
        analyses = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.user_id == user.id).order_by(models.AnalysisRequest.id.desc()).all()
        return templates.TemplateResponse(request=request, name="dashboard.html", context={
            "request": request, 
            "user": user, 
            "analyses": analyses,
            "error": "Yetersiz kredi! Lütfen yeni bir paket satın alın."
        })

    new_request = models.AnalysisRequest(
        user_id=user.id,
        video_url=video_url,
        status="pending"
    )
    # KREDİ DÜŞÜR
    user.credits -= 1
    
    db.add(new_request)
    db.commit()

    # Analiz talebi alınınca e-posta gönder
    background_tasks.add_task(send_analysis_received_email, user.email, user.full_name, video_url)

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/download/{request_id}")
async def download_report(request_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/giris", status_code=status.HTTP_303_SEE_OTHER)
    
    req = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == request_id, models.AnalysisRequest.user_id == user.id).first()
    if not req or req.status != "completed" or not req.report_file_name:
        raise HTTPException(status_code=404, detail="Rapor henüz hazır değil veya bulunamadı.")
    
    file_path = REPORTS_DIR / str(req.id) / req.report_file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Dosya sistemde bulunamadı.")
    
    return FileResponse(path=str(file_path), filename=req.report_file_name)

# --- ADMIN ROUTES ---
@app.get("/girisburdan", response_class=HTMLResponse)
async def admin_login_get(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})

@app.post("/girisburdan")
async def admin_login_post(username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_CREDENTIALS["username"] and password == ADMIN_CREDENTIALS["password"]:
        response = RedirectResponse(url="/admin/analyses", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key=ADMIN_SESSION_NAME, value="authenticated", httponly=True)
        return response
    return RedirectResponse(url="/girisburdan?error=1", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/analyses", response_class=HTMLResponse)
async def admin_dashboard(request: Request, user_id: int = None, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
    
    query = db.query(models.AnalysisRequest)
    if user_id:
        query = query.filter(models.AnalysisRequest.user_id == user_id)
        
    analyses = query.order_by(models.AnalysisRequest.id.desc()).all()
    
    # Check if raw report exists for each request
    for req in analyses:
        raw_path = os.path.join(STORAGE_ROOT, f"raw_analysis_{req.id}.xlsx")
        req.raw_exists = os.path.exists(raw_path)
    
    from database import SQLALCHEMY_DATABASE_URL, IS_PREVIOUSLY_PERSISTENT
    return templates.TemplateResponse(
        request=request, 
        name="admin_analyses.html", 
        context={
            "analyses": analyses,
            "filter_user_id": user_id,
            "storage_status": STORAGE_STATUS,
            "is_persistent": IS_PREVIOUSLY_PERSISTENT,
            "db_url": str(SQLALCHEMY_DATABASE_URL)
        }
    )

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
    
    users = db.query(models.User).order_by(models.User.id.desc()).all()
    return templates.TemplateResponse(
        request=request, 
        name="admin_users.html", 
        context={"users": users}
    )

from youtube_service import fetch_and_generate_raw_report

def bg_generate_raw_report(req_id: int, video_url: str, max_comments: int = 1000):
    try:
        raw_path = os.path.join(STORAGE_ROOT, f"raw_analysis_{req_id}.xlsx")
        print(f"--- [START] Yorum çekme başlatıldı: İstek {req_id} (Limit: {max_comments}) ---")
        fetch_and_generate_raw_report(video_url, raw_path, max_comments=max_comments)
        print(f"--- [SUCCESS] Yorum çekme tamamlandı: İstek {req_id} ---")
    except Exception as e:
        print(f"!!! [ERROR] {req_id} için yorum çekilemedi: {e}")

@app.post("/admin/analyses/{analysis_id}/generate_raw")
async def admin_generate_raw(analysis_id: int, request: Request, background_tasks: BackgroundTasks, max_comments: int = Form(1000), db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated": raise HTTPException(status_code=401)
    
    req = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == analysis_id).first()
    if req:
        # Eğer varsa eskisini sil, yenisini oluştur
        raw_path = os.path.join(STORAGE_ROOT, f"raw_analysis_{analysis_id}.xlsx")
        if os.path.exists(raw_path):
            os.remove(raw_path)
        background_tasks.add_task(bg_generate_raw_report, analysis_id, req.video_url, max_comments)
        
    return RedirectResponse(url="/admin/analyses", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/download_raw/{analysis_id}")
async def admin_download_raw(analysis_id: int, request: Request):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated": raise HTTPException(status_code=401)
    
    raw_path = os.path.join(STORAGE_ROOT, f"raw_analysis_{analysis_id}.xlsx")
    if os.path.exists(raw_path):
        return FileResponse(path=raw_path, filename=f"ham_veriler_{analysis_id}.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    raise HTTPException(status_code=404, detail="Ham veri dosyası henüz hazır değil veya oluşturulamadı.")

@app.post("/admin/update_credits/{user_id}")
async def admin_update_credits(user_id: int, request: Request, credits: int = Form(...), plan: str = Form(...), db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401)
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user:
        user.credits = credits
        user.subscription_plan = plan
        db.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/user/{user_id}/toggle_status")
async def admin_toggle_user_status(user_id: int, request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401)
        
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user:
        user.is_active = not user.is_active
        db.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/user/{user_id}/delete")
async def admin_delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401)
        
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user:
        # Önce kullanıcının tüm analiz taleplerini sil (Constraint hatası almamak için)
        db.query(models.AnalysisRequest).filter(models.AnalysisRequest.user_id == user_id).delete()
        # Kullanıcıyı sil
        db.delete(user)
        db.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/test_email")
async def admin_test_email(request: Request, background_tasks: BackgroundTasks):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
    
    # E-posta kuyruğu (admin@vid-insight.com adresine gider)
    background_tasks.add_task(send_report_email, "admin@vid-insight.com", "Yönetici Testi", "SİSTEM TEST VİDEOSU")
    return {"status": "ok", "message": "Test e-postası kuyruğa eklendi. Lütfen admin@vid-insight.com adresini kontrol edin."}

@app.post("/admin/upload_report/{analysis_id}")
async def upload_report(analysis_id: int, 
                        request: Request,
                        background_tasks: BackgroundTasks,
                        video_title: str = Form(...),
                        admin_note: str = Form(None),
                        report_file: UploadFile = File(...), 
                        db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401, detail="Yetkisiz.")
    
    req = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == analysis_id).first()
    if not req: raise HTTPException(status_code=404)
    
    # Create request specific folder
    req_dir = REPORTS_DIR / str(req.id)
    os.makedirs(req_dir, exist_ok=True)
    
    file_path = req_dir / report_file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(report_file.file, buffer)
    
    req.report_file_name = report_file.filename
    req.video_title = video_title
    req.admin_note = admin_note
    req.status = "completed"
    req.completed_at = datetime.datetime.utcnow()
    db.commit()
    
    # E-posta bildirimini asenkron olarak gönder
    background_tasks.add_task(send_report_email, req.user.email, req.user.full_name, video_title)
    
    return RedirectResponse(url="/admin/analyses", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/download_db")
async def download_db(request: Request):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401)
    
    # Get db file path
    from database import SQLALCHEMY_DATABASE_URL
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite:///"):
        path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")
        if os.path.exists(path):
            return FileResponse(path=path, filename="backup.db")
    
    return {"error": "Veritabanı dosyası bulunamadı."}

@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/")
    response.delete_cookie(ADMIN_SESSION_NAME)
    return response

# --- STRIPE WEBHOOK ---
@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)

    # Ödeme başarılı olduğunda
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        # Kullanıcıyı e-posta veya client_reference_id ile bul
        customer_email = session.get("customer_details", {}).get("email")
        client_reference_id = session.get("client_reference_id")
        
        user = None
        if client_reference_id:
            user = db.query(models.User).filter(models.User.id == int(client_reference_id)).first()
        elif customer_email:
            user = db.query(models.User).filter(models.User.email == customer_email).first()
            
        if user:
            # Ödenen miktara veya ürün adlarına göre kredi tanımla
            # Bu kısımda session["line_items"] veya metadata kullanılabilir.
            # Şimdilik tutara göre basit bir eşleştirme yapalım (Örn: 5 EUR -> 1, 15 EUR -> 5, 20 EUR -> 10)
            amount_total = session.get("amount_total", 0) / 100 # Cents to Euro
            
            if amount_total <= 5:
                user.credits += 1
                user.subscription_plan = "single"
            elif amount_total <= 15:
                user.credits = 5
                user.subscription_plan = "creator"
                user.last_renewal_date = datetime.datetime.utcnow()
            elif amount_total <= 20:
                user.credits = 10
                user.subscription_plan = "agency"
                user.last_renewal_date = datetime.datetime.utcnow()
                
            db.commit()
            print(f"Kredi tanımlandı: {user.email} -> {user.credits} hak.")

    return JSONResponse(content={"status": "success"})

# Root redirect
@app.get("/{path:path}")
async def catch_all(path: str):
    return RedirectResponse(url="/")
