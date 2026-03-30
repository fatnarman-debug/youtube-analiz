from fastapi import FastAPI, Depends, Request, Form, Response, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import os
import models
import traceback
from database import engine, get_db, SessionLocal
from passlib.context import CryptContext

# Absolute paths for Docker stability
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Create database tables
try:
    print(f"Veritabanı tabloları oluşturuluyor... (DB_PATH: {os.getcwd()}/vidinsight.db)")
    models.Base.metadata.create_all(bind=engine)
    print("Tablolar başarıyla hazır.")
except Exception as e:
    print("VERİTABANI HATASI (Startup):")
    traceback.print_exc()

app = FastAPI()

# Setup Templates and Static Files with absolute paths
try:
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    else:
        print(f"UYARI: Static dizini bulunamadı: {STATIC_DIR}")

    if TEMPLATES_DIR.exists():
        templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    else:
        print(f"KRİTİK: Templates dizini bulunamadı: {TEMPLATES_DIR}")
        templates = None
except Exception as e:
    print("STATIC/TEMPLATES HATASI:")
    traceback.print_exc()

# Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Hardcoded Admin credentials as requested
ADMIN_CREDENTIALS = {
    "username": "hadibaslayalım",
    "password": "12345678qw.ASX"
}
ADMIN_SESSION_NAME = "vidinsight_admin_session"

# Detailed Health check endpoint
@app.get("/health")
async def health_check():
    health_status = {
        "status": "ok",
        "app": "vidinsight",
        "version": "1.0.2",
        "checks": {
            "templates": TEMPLATES_DIR.exists(),
            "static": STATIC_DIR.exists(),
            "index_html": (TEMPLATES_DIR / "index.html").exists(),
            "db_engine": engine.name if engine else "error"
        }
    }
    return health_status

# Root route - Landing Page
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    if not templates:
        return HTMLResponse(content="HATA: Şablon sistemi yüklenemedi. (Templates missing)", status_code=500)
    
    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception as e:
        error_msg = f"TEMPLATES HATASI (index.html): {str(e)}"
        print(error_msg)
        traceback.print_exc()
        return HTMLResponse(content=f"Sayfa yüklenirken bir hata oluştu: {error_msg}", status_code=500)

# Form Submission endpoint (Saving to DB)
@app.post("/submit_form")
async def submit_form(
    request: Request,
    Ad_Soyad: str = Form(...),
    Email: str = Form(...),
    Youtube_Link: str = Form(...),
    paket_adi: str = Form(...),
    Aciklama: str = Form(None),
    db: Session = Depends(get_db)
):
    try:
        new_customer = models.Customer(
            full_name=Ad_Soyad,
            email=Email,
            youtube_link=Youtube_Link,
            package=paket_adi,
            description=Aciklama
        )
        db.add(new_customer)
        db.commit()
        db.refresh(new_customer)
        return {"status": "success", "message": "Bilgileriniz başarıyla kaydedildi."}
    except Exception as e:
        print(f"Error saving customer: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Sistemsel bir hata oluştu: {str(e)}")

# Admin Login Route
@app.get("/girisburdan", response_class=HTMLResponse)
async def login_page(request: Request):
    if not templates: return HTMLResponse(content="Templates missing", status_code=500)
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/girisburdan")
async def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...)
):
    if username == ADMIN_CREDENTIALS["username"] and password == ADMIN_CREDENTIALS["password"]:
        redirect_response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        redirect_response.set_cookie(key=ADMIN_SESSION_NAME, value="authenticated")
        return redirect_response
    else:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Geçersiz kullanıcı adı veya şifre!"})

# Admin Dashboard (Restricted)
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")

    if not templates: return HTMLResponse(content="Templates missing", status_code=500)

    try:
        customers = db.query(models.Customer).order_by(models.Customer.created_at.desc()).all()
        return templates.TemplateResponse("admin.html", {"request": request, "customers": customers})
    except Exception as e:
        error_msg = f"ADMIN DASHBOARD HATASI: {str(e)}"
        print(error_msg)
        traceback.print_exc()
        return HTMLResponse(content=error_msg, status_code=500)

# Toggle Account Status
@app.post("/admin/toggle/{customer_id}")
async def toggle_status(request: Request, customer_id: int, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")

    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if customer:
        customer.is_active = not customer.is_active
        db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

# Admin Logout
@app.get("/cikis")
async def logout(response: Response):
    response = RedirectResponse(url="/girisburdan")
    response.delete_cookie(ADMIN_SESSION_NAME)
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
