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
from database import engine, get_db, SessionLocal, STORAGE_STATUS, STORAGE_ROOT, REPORTS_DIR
from auth import get_password_hash, verify_password, create_access_token, decode_access_token
import datetime
import stripe

# Stripe Configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_51K...yazdırmayalım_simdi") # Buraya gerçek secret key gelmeli
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_9kskzuBvWaIY8Kkr3VsnFNZKpfy4RKuN")
stripe.api_key = STRIPE_SECRET_KEY

# Absolute paths for Docker stability
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Create database tables
try:
    models.Base.metadata.create_all(bind=engine)
    # Mevcut veritabanına yeni sütunları eklemek için (Alembic kullanmadığımız için manuel kontrol)
    with engine.connect() as conn:
        from sqlalchemy import text
        print("Veritabanı sütunları kontrol ediliyor...")
        # credits sütunu yoksa ekle
        try: conn.execute(text("ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 1"))
        except Exception as e: print(f"Bilgi: credits sütunu zaten olabilir veya eklenemedi: {e}")
        # subscription_plan sütunu yoksa ekle
        try: conn.execute(text("ALTER TABLE users ADD COLUMN subscription_plan VARCHAR(50) DEFAULT 'free'"))
        except Exception as e: print(f"Bilgi: subscription_plan sütunu zaten olabilir veya eklenemedi: {e}")
        # last_renewal_date sütunu yoksa ekle
        try: conn.execute(text("ALTER TABLE users ADD COLUMN last_renewal_date DATETIME"))
        except Exception as e: print(f"Bilgi: last_renewal_date sütunu zaten olabilir veya eklenemedi: {e}")
        conn.commit()
    print("Veritabanı kontrolü tamamlandı.")
except Exception as e:
    print(f"!!! VERİTABANI HATASI (Startup): {e}")
    traceback.print_exc()

# Stripe Configuration with extra safety
try:
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_9kskzuBvWaIY8Kkr3VsnFNZKpfy4RKuN")
    stripe.api_key = STRIPE_SECRET_KEY
    print("Stripe yapılandırması yüklendi.")
except Exception as e:
    print(f"!!! STRIPE YAPILANDIRMA HATASI: {e}")

app = FastAPI()

# Setup Templates and Static Files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if TEMPLATES_DIR.exists():
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
else:
    templates = None

# Hardcoded Admin
ADMIN_CREDENTIALS = {
    "username": "hadibaslayalım",
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
    return db.query(models.User).filter(models.User.username == username).first()

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
    return templates.TemplateResponse(request=request, name="index.html", context={"user": user})

@app.get("/giris", response_class=HTMLResponse)
async def user_login_get(request: Request, error: str = None, success: bool = False):
    return templates.TemplateResponse(request=request, name="user_login.html", context={"error": error, "success": success})

@app.post("/giris")
async def user_login_post(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    # Email VEYA Username ile giriş
    user = db.query(models.User).filter((models.User.email == email) | (models.User.username == email)).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request=request, name="user_login.html", context={"error": "Geçersiz bilgiler."})
    
    token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key=USER_SESSION_NAME, value=token, httponly=True)
    return response

@app.get("/kayit", response_class=HTMLResponse)
async def signup_get(request: Request, error: str = None):
    return templates.TemplateResponse(request=request, name="signup.html", context={"error": error})

@app.post("/kayit")
async def signup_post(request: Request, 
                      username: str = Form(...),
                      email: str = Form(...),
                      full_name: str = Form(...),
                      password: str = Form(...),
                      db: Session = Depends(get_db)):
    
    # Check if exists
    if db.query(models.User).filter((models.User.username == username) | (models.User.email == email)).first():
        return templates.TemplateResponse(request=request, name="signup.html", context={"error": "Bu kullanıcı adı veya e-posta zaten kullanımda."})
    
    new_user = models.User(
        username=username,
        email=email,
        full_name=full_name,
        password_hash=get_password_hash(password)
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/giris?success=true", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/cikis")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie(USER_SESSION_NAME)
    return response

# --- USER ROUTES ---
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/giris")
    
    analyses = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.user_id == user.id).order_by(models.AnalysisRequest.id.desc()).all()
    
    # Kredileri kontrol et ve yenile
    check_and_renew_credits(user, db)
    
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"user": user, "analyses": analyses})

@app.post("/analyze")
async def create_analysis(request: Request, video_url: str = Form(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/giris")
    
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
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/download/{request_id}")
async def download_report(request_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/giris")
    
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
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
    
    analyses = db.query(models.AnalysisRequest).order_by(models.AnalysisRequest.id.desc()).all()
    from database import SQLALCHEMY_DATABASE_URL, IS_PREVIOUSLY_PERSISTENT
    return templates.TemplateResponse(
        request=request, 
        name="admin_analyses.html", 
        context={
            "analyses": analyses,
            "storage_status": STORAGE_STATUS,
            "is_persistent": IS_PREVIOUSLY_PERSISTENT,
            "db_url": str(SQLALCHEMY_DATABASE_URL)
        }
    )

@app.post("/admin/upload_report/{analysis_id}")
async def upload_report(analysis_id: int, 
                        request: Request,
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
