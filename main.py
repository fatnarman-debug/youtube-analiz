from fastapi import FastAPI, Depends, Request, Form, Response, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os
import models
import traceback
from database import engine, get_db, SessionLocal
from passlib.context import CryptContext

# Create database tables with detailed error logging
try:
    print("Veritabanı tabloları oluşturuluyor...")
    models.Base.metadata.create_all(bind=engine)
    print("Tablolar başarıyla oluşturuldu veya zaten var.")
except Exception as e:
    print("VERİTABANI HATASI (Startup):")
    traceback.print_exc()

app = FastAPI()

# Setup Templates and Static Files
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="templates")
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

# Health check endpoint to verify if the server is alive
@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "vidinsight", "version": "1.0.1"}

# Root route - Landing Page
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception as e:
        print("TEMPLATES HATASI (index.html):")
        traceback.print_exc()
        return HTMLResponse(content="Sayfa yüklenirken bir hata oluştu. Logları kontrol edin.", status_code=500)

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
        raise HTTPException(status_code=500, detail="Sistemsel bir hata oluştu.")

# Admin Login Route (as requested)
@app.get("/girisburdan", response_class=HTMLResponse)
async def login_page(request: Request):
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

    try:
        customers = db.query(models.Customer).order_by(models.Customer.created_at.desc()).all()
        return templates.TemplateResponse("admin.html", {"request": request, "customers": customers})
    except Exception as e:
        print("ADMIN DASHBOARD HATASI:")
        traceback.print_exc()
        return HTMLResponse(content="Dashboard yüklenirken hata oluştu.", status_code=500)

# Toggle Account Status (Active/Passive)
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
