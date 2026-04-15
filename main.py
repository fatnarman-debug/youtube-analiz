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
import re
import unicodedata
import anthropic

def slugify(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)

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
    # Migration: raw_status kolonu yoksa ekle
    from sqlalchemy import text as sa_text
    _mig_db = SessionLocal()
    try:
        _mig_db.execute(sa_text("ALTER TABLE analysis_requests ADD COLUMN raw_status VARCHAR(20) DEFAULT 'processing'"))
        _mig_db.commit()
        print("[Migration] raw_status kolonu eklendi.")
    except Exception:
        pass  # Kolon zaten varsa hata yoksay
    finally:
        _mig_db.close()
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

def t(request: Request, key: str, default: str = None):
    lang = get_locale(request)
    translations = load_translations()
    # 1. Choose language, 2. if not found, choose 'tr', 3. if not found, choose 'default', 4. if not found, return 'key'
    result = translations.get(lang, {}).get(key)
    if result is None:
        result = translations.get("tr", {}).get(key)
    if result is None:
        result = default if default is not None else key
    return result

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
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@vid-insight.com")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@vid-insight.com")

async def _send_email(message: EmailMessage):
    """SMTP sunucusu üzerinden e-posta gönderir. Hata durumunda log tutar."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("!!! SMTP ayarları eksik (SMTP_USER/SMTP_PASSWORD), e-posta gönderilemedi.")
        return

    if "From" not in message:
        message["From"] = SMTP_FROM
    if "Reply-To" not in message:
        message["Reply-To"] = SMTP_USER
    if "Message-ID" not in message:
        import uuid
        domain = SMTP_USER.split("@")[-1]
        message["Message-ID"] = f"<{uuid.uuid4().hex}@{domain}>"
    if "List-Unsubscribe" not in message:
        message["List-Unsubscribe"] = f"<mailto:{SMTP_USER}?subject=unsubscribe>"
    if "X-Mailer" not in message:
        message["X-Mailer"] = "VidInsight Mailer"

    # Port deneme listesi: [(Port, use_tls, start_tls), ...]
    ports_to_try = [
        (SMTP_PORT, False, True),  # STARTTLS (Genelde 587)
        (465, True, False),        # Direct SSL (Eski ama stabil)
    ]

    last_error = None
    for port, use_tls, start_tls in ports_to_try:
        try:
            print(f"--- E-posta gönderiliyor ({'SSL' if use_tls else 'STARTTLS'} | Port: {port})...")
            await aiosmtplib.send(
                message,
                hostname=SMTP_HOST,
                port=port,
                username=SMTP_USER,
                password=SMTP_PASSWORD,
                use_tls=use_tls,
                start_tls=start_tls,
                validate_certs=False, # Self-signed sertifikalar için esneklik
                timeout=15
            )
            print(f"--- E-posta başarıyla gönderildi: {message['To']} (Port: {port})")
            return # Başarılı ise çık
        except Exception as e:
            last_error = e
            print(f"!!! Port {port} hatası: {str(e)}")

    print(f"!!! E-posta gönderimi Topyekün BAŞARISIZ. Alıcı: {message['To']} | Hata: {last_error}")

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

    await _send_email(message)

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
    await _send_email(message)

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
                    <p>Ekibimiz şu an yorumları tarıyor. Analiz tamamlandığında size tekrar haber vereceğiz.</p>
                    <p>Güncel durumu panelinizden takip edebilirsiniz.</p>
                </div>
            </div>
        </body>
    </html>
    """
    message.set_content("Videonuzu aldık, analiz başlıyor!")
    message.add_alternative(html_content, subtype="html")
    await _send_email(message)

async def send_admin_new_user_email(user_email: str, user_name: str):
    """Admin'e yeni kullanıcı kaydı bildirimi gönderir."""
    if not SMTP_USER or not SMTP_PASSWORD: return
    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = ADMIN_EMAIL
    message["Subject"] = f"🆕 Yeni Kayıt: {user_name}"
    html = f"""
    <html><body style="font-family:sans-serif;color:#333;">
    <div style="max-width:500px;margin:0 auto;border:1px solid #eee;border-radius:10px;overflow:hidden;">
        <div style="background:#0F172A;padding:16px 20px;color:#F59E0B;font-size:1.1rem;font-weight:700;">VidInsight — Yeni Üye</div>
        <div style="padding:20px;">
            <p>Yeni bir kullanıcı kaydoldu:</p>
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:6px 0;color:#666;">İsim</td><td style="font-weight:700;">{user_name}</td></tr>
                <tr><td style="padding:6px 0;color:#666;">E-posta</td><td style="font-weight:700;">{user_email}</td></tr>
            </table>
        </div>
    </div>
    </body></html>
    """
    message.set_content(f"Yeni kayıt: {user_name} ({user_email})")
    message.add_alternative(html, subtype="html")
    await _send_email(message)

async def send_purchase_confirmation_email(user_email: str, user_name: str, plan: str, credits: int, amount: float):
    """Satın alma sonrası kullanıcıya onay ve admin'e bildirim gönderir."""
    if not SMTP_USER or not SMTP_PASSWORD: return

    # --- Kullanıcıya onay ---
    user_msg = EmailMessage()
    user_msg["From"] = SMTP_FROM
    user_msg["To"] = user_email
    user_msg["Subject"] = "✅ Ödemeniz Alındı — VidInsight"
    user_html = f"""
    <html><body style="font-family:sans-serif;color:#333;">
    <div style="max-width:560px;margin:0 auto;border:1px solid #eee;border-radius:12px;overflow:hidden;">
        <div style="background:#0F172A;padding:20px;text-align:center;">
            <span style="color:#F59E0B;font-size:1.4rem;font-weight:800;">VidInsight</span>
        </div>
        <div style="padding:30px;">
            <h2 style="color:#10b981;margin-top:0;">Ödemeniz Başarıyla Alındı! 🎉</h2>
            <p>Merhaba <strong>{user_name}</strong>,</p>
            <p><strong>{plan.upper()}</strong> paketiniz aktive edildi. Hesabınıza <strong>{credits} kredi</strong> tanımlandı.</p>
            <div style="background:#f8fafc;border-radius:8px;padding:16px;margin:20px 0;">
                <div style="font-size:0.85rem;color:#666;">Ödenen Tutar</div>
                <div style="font-size:1.5rem;font-weight:800;color:#0F172A;">€{amount:.2f}</div>
            </div>
            <a href="https://vid-insight.com/dashboard"
               style="display:inline-block;background:#F59E0B;color:#0F172A;font-weight:700;padding:12px 28px;border-radius:8px;text-decoration:none;">
                Panele Git →
            </a>
            <p style="color:#999;font-size:0.8rem;margin-top:20px;">Teşekkür ederiz. Her türlü sorunuz için bize ulaşabilirsiniz.</p>
        </div>
    </div>
    </body></html>
    """
    user_msg.set_content(f"Ödemeniz alındı. {credits} kredi hesabınıza tanımlandı.")
    user_msg.add_alternative(user_html, subtype="html")
    await _send_email(user_msg)

    # --- Admin'e satın alma bildirimi ---
    admin_msg = EmailMessage()
    admin_msg["From"] = SMTP_FROM
    admin_msg["To"] = ADMIN_EMAIL
    admin_msg["Subject"] = f"💰 Yeni Satış: {plan.upper()} — {user_name}"
    admin_html = f"""
    <html><body style="font-family:sans-serif;color:#333;">
    <div style="max-width:500px;margin:0 auto;border:1px solid #eee;border-radius:10px;overflow:hidden;">
        <div style="background:#0F172A;padding:16px 20px;color:#F59E0B;font-size:1.1rem;font-weight:700;">VidInsight — Yeni Satış</div>
        <div style="padding:20px;">
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:6px 0;color:#666;">Kullanıcı</td><td style="font-weight:700;">{user_name}</td></tr>
                <tr><td style="padding:6px 0;color:#666;">E-posta</td><td style="font-weight:700;">{user_email}</td></tr>
                <tr><td style="padding:6px 0;color:#666;">Paket</td><td style="font-weight:700;">{plan.upper()}</td></tr>
                <tr><td style="padding:6px 0;color:#666;">Kredi</td><td style="font-weight:700;">{credits}</td></tr>
                <tr><td style="padding:6px 0;color:#666;">Tutar</td><td style="font-weight:700;color:#10b981;">€{amount:.2f}</td></tr>
            </table>
        </div>
    </div>
    </body></html>
    """
    admin_msg.set_content(f"Yeni satış: {user_name} | {plan.upper()} | €{amount:.2f}")
    admin_msg.add_alternative(admin_html, subtype="html")
    await _send_email(admin_msg)

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
@app.get("/robots.txt")
async def robots_txt():
    content = """User-agent: *
Allow: /
Allow: /blog
Allow: /blog/
Allow: /gizlilik-politikasi

Disallow: /giris
Disallow: /kayit
Disallow: /dashboard
Disallow: /cikis
Disallow: /admin/
Disallow: /girisburdan
Disallow: /download/
Disallow: /analyze
Disallow: /stripe-webhook
Disallow: /debug

Sitemap: https://vid-insight.com/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")

@app.get("/sitemap.xml")
async def sitemap_xml(db: Session = Depends(get_db)):
    blog_posts = db.query(models.BlogPost).filter(models.BlogPost.is_published == True).all()

    urls = [
        {"loc": "https://vid-insight.com/", "priority": "1.0", "changefreq": "weekly"},
        {"loc": "https://vid-insight.com/blog", "priority": "0.8", "changefreq": "weekly"},
        {"loc": "https://vid-insight.com/gizlilik-politikasi", "priority": "0.3", "changefreq": "yearly"},
    ]
    for post in blog_posts:
        urls.append({
            "loc": f"https://vid-insight.com/blog/{post.slug}",
            "priority": "0.7",
            "changefreq": "monthly",
            "lastmod": post.created_at.strftime("%Y-%m-%d") if post.created_at else ""
        })

    url_entries = ""
    for u in urls:
        lastmod_tag = f"\n    <lastmod>{u['lastmod']}</lastmod>" if u.get("lastmod") else ""
        url_entries += f"""  <url>
    <loc>{u['loc']}</loc>{lastmod_tag}
    <changefreq>{u['changefreq']}</changefreq>
    <priority>{u['priority']}</priority>
  </url>\n"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{url_entries}</urlset>"""
    return Response(content=xml, media_type="application/xml")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"user": user}
    )

@app.get("/gizlilik-politikasi", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    return templates.TemplateResponse(request=request, name="privacy.html", context={})

@app.get("/blog", response_class=HTMLResponse)
async def blog_list(request: Request, db: Session = Depends(get_db)):
    posts = db.query(models.BlogPost).filter(models.BlogPost.is_published == True).order_by(models.BlogPost.created_at.desc()).all()
    user = get_current_user(request, db)
    return templates.TemplateResponse(
        request=request, 
        name="blog.html", 
        context={"user": user, "posts": posts, "t": t}
    )

@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    post = db.query(models.BlogPost).filter(models.BlogPost.slug == slug, models.BlogPost.is_published == True).first()
    if not post:
        raise HTTPException(status_code=404)
    user = get_current_user(request, db)
    return templates.TemplateResponse(
        request=request, 
        name="blog_detail.html", 
        context={"user": user, "post": post, "t": t}
    )

@app.get("/giris", response_class=HTMLResponse)
async def user_login_get(request: Request, error: str = None, success: bool = False):
    return templates.TemplateResponse(request=request, name="user_login.html", context={"error": error, "success": success})

@app.post("/giris")
async def user_login_post(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    # Email VEYA Username ile giriş
    user = db.query(models.User).filter((models.User.email == email) | (models.User.username == email)).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request=request, name="user_login.html", context={"error": "err_invalid_creds"})
    
    if not user.is_active:
        return templates.TemplateResponse(request=request, name="user_login.html", context={"error": "err_user_inactive"})
    
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
            return templates.TemplateResponse(request=request, name="signup.html", context={
                "request": request, "error": "err_user_exists"
            })

        new_user = models.User(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=get_password_hash(password)
        )
        new_user.credits = 0
        new_user.subscription_plan = "free"
        new_user.last_renewal_date = datetime.datetime.utcnow()

        db.add(new_user)
        db.commit()

        # Kayıt sonrası HOŞ GELDİN e-postası + admin bildirimi
        background_tasks.add_task(send_welcome_email, email, full_name)
        background_tasks.add_task(send_admin_new_user_email, email, full_name)

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
            "error": "err_insufficient_credits"
        })

    # Dinamik Başlık Çekme İşlemi
    fetched_title = "İşleniyor..."
    try:
        import youtube_service
        title = youtube_service.get_video_title(video_url)
        if title:
            fetched_title = title
    except Exception as e:
        pass

    new_request = models.AnalysisRequest(
        user_id=user.id,
        video_url=video_url,
        video_title=fetched_title,
        status="pending"
    )
    # KREDİ DÜŞÜR
    user.credits -= 1
    
    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    # Otomatik analiz başlat
    background_tasks.add_task(bg_generate_raw_report, new_request.id, video_url, 5000)

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

@app.get("/admin/blog", response_class=HTMLResponse)
async def admin_blog_list(request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
    posts = db.query(models.BlogPost).order_by(models.BlogPost.created_at.desc()).all()
    return templates.TemplateResponse(
        request=request, 
        name="admin_blog.html", 
        context={"posts": posts}
    )

@app.get("/admin/blog/new", response_class=HTMLResponse)
async def admin_blog_new(request: Request):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
    return templates.TemplateResponse(
        request=request, 
        name="admin_blog_edit.html", 
        context={"post": None}
    )

@app.post("/admin/blog/save")
async def admin_blog_save(request: Request, id: int = Form(None), title: str = Form(...), content: str = Form(...), is_published: bool = Form(False), db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401)
    
    if id:
        post = db.query(models.BlogPost).filter(models.BlogPost.id == id).first()
        post.title = title
        post.content = content
        post.is_published = is_published
    else:
        slug = slugify(title)
        # Check for slug collision
        base_slug = slug
        counter = 1
        while db.query(models.BlogPost).filter(models.BlogPost.slug == slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1
        post = models.BlogPost(title=title, slug=slug, content=content, is_published=is_published)
        db.add(post)
    
    db.commit()
    return RedirectResponse(url="/admin/blog", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/blog/edit/{id}", response_class=HTMLResponse)
async def admin_blog_edit(id: int, request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
    post = db.query(models.BlogPost).filter(models.BlogPost.id == id).first()
    return templates.TemplateResponse(
        request=request, 
        name="admin_blog_edit.html", 
        context={"post": post}
    )

@app.post("/admin/blog/delete/{id}")
async def admin_blog_delete(id: int, request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401)
    db.query(models.BlogPost).filter(models.BlogPost.id == id).delete()
    db.commit()
    return RedirectResponse(url="/admin/blog", status_code=status.HTTP_303_SEE_OTHER)

from youtube_service import fetch_and_generate_raw_report

def generate_ai_report_html(req_id: int, raw_path: str, video_title: str) -> str:
    """Excel verilerini okur, Claude API ile Türkçe HTML rapor üretir, dosyaya kaydeder."""
    import pandas as pd

    xl = pd.ExcelFile(raw_path)

    # İstatistikler
    df_stats = xl.parse("Istatistikler")
    stats_text = df_stats.to_string(index=False)

    # En beğenilen yorumlar (ilk 15)
    df_top = xl.parse("En Begilen Yorumlar").head(15)
    top_text = df_top[['kullanici', 'yorum', 'begeni_sayisi', 'duygu']].to_string(index=False)

    # Öneri / Eleştiri özeti (ilk 20 satır)
    df_feedback = xl.parse("Oneri_Elestiri_Ozeti").head(20)
    feedback_text = df_feedback.to_string(index=False)

    # Küfür içeren yorum sayısı
    df_profane = xl.parse("Kufur Iceren Yorumlar")
    profane_count = len(df_profane[df_profane['yorum'] != '-'])

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY tanımlı değil.")

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""Sen bir YouTube yorum analizi uzmanısın. Aşağıdaki ham verilere dayanarak profesyonel bir analiz raporu hazırla.

Video Başlığı: {video_title}

--- İSTATİSTİKLER ---
{stats_text}

--- EN BEĞENİLEN YORUMLAR (Top 15) ---
{top_text}

--- ÖNERİ / ELEŞTİRİ ÖZETİ ---
{feedback_text}

--- KÜFÜR / SALDIRGAN İÇERİK SAYISI ---
{profane_count} yorum

Aşağıdaki JSON formatında yanıt ver (başka hiçbir şey yazma, sadece JSON):
{{
  "yonetici_ozeti": "3-4 cümlelik genel değerlendirme. İzleyici kitlesinin genel tutumu, öne çıkan temalar.",
  "duygu_analizi_yorumu": "Duygu dağılımını yorumla. Olumlu/olumsuz/nötr oranlarının ne anlama geldiğini açıkla.",
  "one_cikan_elestiriler": ["eleştiri 1", "eleştiri 2", "eleştiri 3"],
  "izleyici_onerileri": ["öneri 1", "öneri 2", "öneri 3"],
  "en_etkili_yorumlar": [
    {{"yorum": "yorum metni", "neden_onemli": "kısa açıklama"}},
    {{"yorum": "yorum metni", "neden_onemli": "kısa açıklama"}},
    {{"yorum": "yorum metni", "neden_onemli": "kısa açıklama"}}
  ],
  "icerik_onerileri": ["bir sonraki video için öneri 1", "öneri 2", "öneri 3", "öneri 4"],
  "kufur_degerlendirmesi": "Küfür/saldırgan yorum oranını değerlendir ve ne yapılması gerektiğini belirt.",
  "sonuc": "2-3 cümlelik kapanış. Kanalın güçlü yönleri ve dikkat edilmesi gerekenler."
}}"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_json = message.content[0].text.strip()
    # Bazen model ```json bloğu içinde döner, temizle
    if raw_json.startswith("```"):
        raw_json = re.sub(r"```(?:json)?", "", raw_json).strip().rstrip("```").strip()

    data = json.loads(raw_json)

    # Etkili yorumları HTML listesine çevir
    etkili_yorumlar_html = ""
    for item in data.get("en_etkili_yorumlar", []):
        etkili_yorumlar_html += f"""
        <div class="comment-card">
          <p class="comment-text">"{item['yorum']}"</p>
          <p class="comment-note">→ {item['neden_onemli']}</p>
        </div>"""

    elestiri_items = "".join(f"<li>{e}</li>" for e in data.get("one_cikan_elestiriler", []))
    oneri_items    = "".join(f"<li>{o}</li>" for o in data.get("izleyici_onerileri", []))
    icerik_items   = "".join(f"<li>{i}</li>" for i in data.get("icerik_onerileri", []))

    uretim_tarihi = datetime.datetime.utcnow().strftime("%d.%m.%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Yorum Analiz Raporu — {video_title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f6f9; color: #1a1a2e; line-height: 1.7; }}
  .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%); color: #fff; padding: 40px 48px; }}
  .header h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 6px; }}
  .header .meta {{ font-size: 0.85rem; opacity: 0.7; }}
  .badge {{ display: inline-block; background: #3b82f6; color: #fff; font-size: 0.75rem; padding: 3px 10px; border-radius: 20px; margin-right: 8px; }}
  .container {{ max-width: 860px; margin: 0 auto; padding: 36px 24px; }}
  .section {{ background: #fff; border-radius: 12px; padding: 28px 32px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .section h2 {{ font-size: 1.05rem; font-weight: 700; color: #0f172a; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #e2e8f0; display: flex; align-items: center; gap: 8px; }}
  .section h2 .icon {{ font-size: 1.2rem; }}
  .ozet-text {{ font-size: 0.97rem; color: #334155; }}
  ul {{ padding-left: 20px; }}
  ul li {{ margin-bottom: 8px; font-size: 0.95rem; color: #334155; }}
  .comment-card {{ background: #f8fafc; border-left: 4px solid #3b82f6; border-radius: 6px; padding: 14px 18px; margin-bottom: 12px; }}
  .comment-text {{ font-size: 0.92rem; color: #1e293b; font-style: italic; margin-bottom: 6px; }}
  .comment-note {{ font-size: 0.85rem; color: #64748b; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 14px; margin-top: 4px; }}
  .stat-card {{ background: #f1f5f9; border-radius: 8px; padding: 16px; text-align: center; }}
  .stat-card .val {{ font-size: 1.5rem; font-weight: 800; color: #0f172a; }}
  .stat-card .lbl {{ font-size: 0.78rem; color: #64748b; margin-top: 2px; }}
  .kufur-box {{ background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 14px 18px; font-size: 0.93rem; color: #991b1b; }}
  .footer {{ text-align: center; font-size: 0.78rem; color: #94a3b8; padding: 24px; }}
  @media print {{ body {{ background: #fff; }} .section {{ box-shadow: none; border: 1px solid #e2e8f0; }} }}
</style>
</head>
<body>
<div class="header">
  <div class="meta"><span class="badge">VidInsight</span> Otomatik Analiz Raporu &nbsp;·&nbsp; {uretim_tarihi} UTC</div>
  <h1 style="margin-top:12px">{video_title}</h1>
</div>

<div class="container">

  <div class="section">
    <h2><span class="icon">📋</span> Yönetici Özeti</h2>
    <p class="ozet-text">{data['yonetici_ozeti']}</p>
  </div>

  <div class="section">
    <h2><span class="icon">💬</span> Duygu Analizi</h2>
    <p class="ozet-text">{data['duygu_analizi_yorumu']}</p>
  </div>

  <div class="section">
    <h2><span class="icon">⚠️</span> Öne Çıkan Eleştiriler</h2>
    <ul>{elestiri_items}</ul>
  </div>

  <div class="section">
    <h2><span class="icon">💡</span> İzleyici Önerileri</h2>
    <ul>{oneri_items}</ul>
  </div>

  <div class="section">
    <h2><span class="icon">⭐</span> En Etkili Yorumlar</h2>
    {etkili_yorumlar_html}
  </div>

  <div class="section">
    <h2><span class="icon">🎬</span> Bir Sonraki Video İçin Öneriler</h2>
    <ul>{icerik_items}</ul>
  </div>

  <div class="section">
    <h2><span class="icon">🚨</span> Küfür / Saldırgan İçerik</h2>
    <div class="kufur-box">{data['kufur_degerlendirmesi']}</div>
  </div>

  <div class="section">
    <h2><span class="icon">✅</span> Sonuç</h2>
    <p class="ozet-text">{data['sonuc']}</p>
  </div>

</div>
<div class="footer">Bu rapor VidInsight tarafından otomatik olarak oluşturulmuştur · vid-insight.com</div>
</body>
</html>"""

    report_dir = REPORTS_DIR / str(req_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "rapor.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    return "rapor.html"


def bg_generate_raw_report(req_id: int, video_url: str, max_comments: int = 5000):
    db = SessionLocal()
    try:
        raw_path = os.path.join(STORAGE_ROOT, f"raw_analysis_{req_id}.xlsx")
        print(f"--- [START] Yorum çekme başlatıldı: İstek {req_id} (Limit: {max_comments}) ---")
        fetch_and_generate_raw_report(video_url, raw_path, max_comments=max_comments)
        print(f"--- [SUCCESS] Yorum çekme tamamlandı: İstek {req_id} ---")

        req = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == req_id).first()
        if req:
            req.raw_status = "ready"
            db.commit()

        # Claude API ile otomatik rapor oluştur
        print(f"--- [AI] Rapor oluşturuluyor: İstek {req_id} ---")
        video_title = req.video_title if req else "Bilinmiyor"
        report_filename = generate_ai_report_html(req_id, raw_path, video_title)

        if req:
            req.status = "completed"
            req.report_file_name = report_filename
            req.completed_at = datetime.datetime.utcnow()
            db.commit()
        print(f"--- [AI SUCCESS] Rapor hazır: İstek {req_id} ---")

    except Exception as e:
        print(f"!!! [ERROR] {req_id} için işlem başarısız: {e}")
        req = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == req_id).first()
        if req:
            req.raw_status = "failed"
            db.commit()
    finally:
        db.close()

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
async def admin_test_email(request: Request, to: str = ""):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")

    target = to or ADMIN_EMAIL
    result = {"smtp_host": SMTP_HOST, "smtp_port": SMTP_PORT, "smtp_user": SMTP_USER, "target": target}

    try:
        msg = EmailMessage()
        msg["From"] = SMTP_FROM
        msg["To"] = target
        msg["Subject"] = "VidInsight SMTP Test"
        msg.set_content("Bu bir test mailidir.")
        msg.add_alternative("<h2>VidInsight SMTP Test</h2><p>Bağlantı başarılı!</p>", subtype="html")

        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            use_tls=False,
            start_tls=True,
            validate_certs=False,
            timeout=20
        )
        result["status"] = "BAŞARILI"
        result["message"] = f"Mail gönderildi → {target}"
    except Exception as e:
        result["status"] = "HATA"
        result["message"] = str(e)

    return result

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

async def bg_send_mass_email(subject: str, content_html: str, user_list: list):
    for u in user_list:
        try:
            message = EmailMessage()
            message["From"] = SMTP_FROM
            message["To"] = u.email
            message["Subject"] = subject
            
            wrapped_html = f"""
            <html>
                <body style="font-family: sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 10px; overflow: hidden;">
                        <div style="background: #0F172A; padding: 20px; text-align: center; color: white;">
                            <h1 style="margin:0;">VidInsight</h1>
                        </div>
                        <div style="padding: 30px;">
                            {content_html}
                        </div>
                    </div>
                </body>
            </html>
            """
            # Düz metin versiyonu HTML ile uyumlu olsun (spam filtrelerini geçmek için)
            import re as _re
            plain_text = _re.sub(r'<[^>]+>', '', content_html).strip()
            plain_text = _re.sub(r'\n{3,}', '\n\n', plain_text)
            message.set_content(plain_text)
            message.add_alternative(wrapped_html, subtype="html")
            await _send_email(message)
        except Exception as e:
            print(f"Toplu Mail Hatasi -> {u.email}: {e}")

@app.get("/admin/marketing", response_class=HTMLResponse)
async def admin_marketing_get(request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
    
    user_count = db.query(models.User).filter(models.User.is_active == True).count()
    return templates.TemplateResponse(request=request, name="admin_marketing.html", context={"user_count": user_count})

@app.post("/admin/marketing/send")
async def admin_marketing_post(request: Request, background_tasks: BackgroundTasks, subject: str = Form(...), content_html: str = Form(...), target: str = Form("all"), specific_emails: str = Form(""), db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401)

    if target == "specific":
        email_list = [e.strip() for e in specific_emails.split(",") if e.strip()]
        print(f"[MARKETING] Hedef: specific | Girilen e-postalar: {email_list}")
        # Doğrudan e-posta listesinden sahte user nesneleri oluştur
        class _FakeUser:
            def __init__(self, email): self.email = email
        target_users = [_FakeUser(e) for e in email_list]
    else:
        target_users = db.query(models.User).filter(models.User.is_active == True).all()

    print(f"[MARKETING] Gönderilecek kişi sayısı: {len(target_users)} | Hedef: {target}")

    if target_users:
        print(f"[MARKETING] Arka plan görevi başlatılıyor...")
        background_tasks.add_task(bg_send_mass_email, subject, content_html, target_users)
    else:
        print(f"[MARKETING] UYARI: Gönderilecek kullanıcı bulunamadı!")

    return RedirectResponse(url="/admin/marketing?success=1", status_code=status.HTTP_303_SEE_OTHER)

# --- STRIPE WEBHOOK ---
@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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
            elif amount_total <= 25:
                user.credits = 10
                user.subscription_plan = "agency"
                user.last_renewal_date = datetime.datetime.utcnow()
            else:
                user.credits += 50
                user.subscription_plan = "enterprise"
                user.last_renewal_date = datetime.datetime.utcnow()
                
            db.commit()
            print(f"Kredi tanımlandı: {user.email} -> {user.credits} hak.")
            background_tasks.add_task(
                send_purchase_confirmation_email,
                user.email, user.full_name, user.subscription_plan, user.credits, amount_total
            )

    return JSONResponse(content={"status": "success"})

# Root redirect
@app.get("/{path:path}")
async def catch_all(path: str):
    return RedirectResponse(url="/")
