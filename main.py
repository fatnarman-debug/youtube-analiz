from fastapi import FastAPI, Depends, Request, Form, Response, HTTPException, status, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import os
import models
import traceback
from database import engine, get_db, SessionLocal
from auth import get_password_hash, verify_password, create_access_token, decode_access_token
from youtube_analyzer import YouTubeCommentAnalyzer
import datetime

# Absolute paths for Docker stability
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Create database tables
try:
    # database.py zaten yolu yazdırdığı için burada sadece tabloları hazırlıyoruz
    models.Base.metadata.create_all(bind=engine)
    print("Veritabanı tabloları hazır.")
except Exception as e:
    print("!!! VERİTABANI HATASI (Startup):")
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

# Hardcoded Admin credentials as requested
ADMIN_CREDENTIALS = {
    "username": "hadibaslayalım",
    "password": "12345678qw.ASX"
}
ADMIN_SESSION_NAME = "vidinsight_admin_session"
USER_SESSION_NAME = "vidinsight_user_session"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# Background Worker
def process_analysis(request_id: int):
    # Separate session for background task
    db = SessionLocal()
    req = None
    try:
        req = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == request_id).first()
        if not req: return

        # Check for API Key
        if not YOUTUBE_API_KEY or YOUTUBE_API_KEY.strip() == "":
            req.status = "error"
            req.error_message = "YouTube API Key eksik. Lütfen Coolify Environment Variables kısmına YOUTUBE_API_KEY ekleyin."
            db.commit()
            return

        req.status = "processing"
        req.error_message = None
        db.commit()

        # Initialize analyzer
        analyzer = YouTubeCommentAnalyzer(YOUTUBE_API_KEY)
        video_id = analyzer.extract_video_id(req.video_url)
        if not video_id:
            req.status = "error"
            req.error_message = "Geçersiz YouTube URL'si."
            db.commit()
            return

        req.video_id = video_id
        analyzer.video_id = video_id
        
        # Step 1: Collect
        if not analyzer.collect_comments(max_comments=200): # max 200 for stability
            req.status = "error"
            req.error_message = getattr(analyzer, 'error_log', 'Yorumlar toplanamadı (video yorumlara kapalı olabilir veya API kotası dolmuş olabilir).')
            db.commit()
            return
            
        # Step 2: Analyze
        req.video_title = analyzer.video_title
        analyzer.run_full_analysis(method='turkish')
        summary = analyzer.generate_summary_text()
        
        # Step 3: Files (Excel & PDF)
        reports_dir = STATIC_DIR / "reports"
        if not reports_dir.exists(): reports_dir.mkdir(parents=True)
        
        excel_filename = f"analiz_{request_id}_{video_id}.xlsx"
        pdf_filename = f"analiz_{request_id}_{video_id}.pdf"
        
        excel_path = reports_dir / excel_filename
        pdf_path = reports_dir / pdf_filename
        
        analyzer.create_excel_report(output_path=str(excel_path))
        analyzer.create_pdf_report(output_path=str(pdf_path))
        
        # Step 4: Report Entry
        # Update existing report if it exists (for retries)
        report = db.query(models.Report).filter(models.Report.analysis_id == req.id).first()
        if report:
            report.excel_path = f"/static/reports/{excel_filename}"
            report.pdf_path = f"/static/reports/{pdf_filename}"
            report.summary_text = summary
        else:
            new_report = models.Report(
                analysis_id=req.id,
                excel_path=f"/static/reports/{excel_filename}",
                pdf_path=f"/static/reports/{pdf_filename}",
                summary_text=summary
            )
            db.add(new_report)
        
        req.status = "completed"
        req.completed_at = datetime.datetime.utcnow()
        db.commit()

    except Exception as e:
        print(f"BACKGROUND TASK ERROR (Request {request_id}):")
        traceback.print_exc()
        if req:
            db.rollback()
            req.status = "error"
            req.error_message = f"Sistemsel Hata: {str(e)}"
            db.commit()
    finally:
        db.close()

# Helper for current user
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(USER_SESSION_NAME)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.query(models.User).filter(models.User.id == int(user_id)).first()

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
        # Modern TemplateResponse signature for Starlette 0.28+
        return templates.TemplateResponse(
            request=request, 
            name="index.html", 
            context={}
        )
    except Exception as e:
        full_error = traceback.format_exc()
        print(f"TEMPLATES HATASI (index.html):\n{full_error}")
        return HTMLResponse(
            content=f"<h1>Sayfa Yükleme Hatası</h1><p>{str(e)}</p><pre>{full_error}</pre>", 
            status_code=500
        )

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

# ==================== CUSTOMER AUTH ROUTES ====================

@app.get("/kayit", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse(request=request, name="signup.html", context={})

@app.post("/kayit")
async def signup(
    request: Request,
    Ad_Soyad: str = Form(...),
    Email: str = Form(...),
    Sifre: str = Form(...),
    db: Session = Depends(get_db)
):
    # Check if user exists
    existing_user = db.query(models.User).filter(models.User.email == Email).first()
    if existing_user:
        return templates.TemplateResponse(
            request=request, 
            name="signup.html", 
            context={"error": "Bu e-posta adresi zaten kayıtlı."}
        )
    
    hashed_sifre = get_password_hash(Sifre)
    new_user = models.User(
        full_name=Ad_Soyad,
        email=Email,
        hashed_password=hashed_sifre,
        credits_remaining=1, # 1 Trial credit
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return RedirectResponse(url="/giris?success=1", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/giris", response_class=HTMLResponse)
async def user_login_page(request: Request, success: int = 0):
    return templates.TemplateResponse(
        request=request, 
        name="user_login.html", 
        context={"success": success}
    )

@app.post("/giris")
async def user_login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        print(f"Giriş Başarısız: {email} (Kullanıcı Bulunamadı veya Yanlış Şifre)")
        return templates.TemplateResponse(
            request=request, 
            name="user_login.html", 
            context={"error": "Geçersiz e-posta veya şifre!"}
        )
    
    # Create token
    access_token = create_access_token(data={"sub": str(user.id)})
    
    redirect_response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    redirect_response.set_cookie(
        key=USER_SESSION_NAME, 
        value=access_token, 
        httponly=True, 
        secure=request.url.scheme == "https", # Secure if HTTPS
        samesite="lax",
        max_age=60*60*24*7 # 1 week
    )
    return redirect_response

@app.get("/cikisyap")
async def user_logout(response: Response):
    response = RedirectResponse(url="/giris")
    response.delete_cookie(USER_SESSION_NAME)
    return response

# ==================== CUSTOMER DASHBOARD ROUTES ====================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/giris")

    # Fetch user's analyses
    recent_analyses = db.query(models.AnalysisRequest).filter(
        models.AnalysisRequest.user_id == user.id
    ).order_by(models.AnalysisRequest.created_at.desc()).limit(10).all()

    # Get active package details
    package = user.package if user.package else None
    
    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html", 
        context={
            "user": user,
            "analyses": recent_analyses,
            "package": package
        }
    )

@app.post("/dashboard/submit")
async def submit_analysis(
    request: Request,
    background_tasks: BackgroundTasks,
    video_url: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Lütfen giriş yapın.")

    # Check credits
    if user.credits_remaining <= 0:
        return JSONResponse(
            status_code=400, 
            content={"status": "error", "message": "Analiz hakkınız bitmiştir. Lütfen yeni paket alın."}
        )

    # Simple URL validation
    if "youtube.com" not in video_url and "youtu.be" not in video_url:
        return JSONResponse(
            status_code=400, 
            content={"status": "error", "message": "Geçerli bir YouTube linki giriniz."}
        )

    # Create request
    new_request = models.AnalysisRequest(
        user_id=user.id,
        video_url=video_url,
        status="pending"
    )
    db.add(new_request)
    
    # Deduct credit
    user.credits_remaining -= 1
    
    db.commit()
    db.refresh(new_request)

    # Start Background Processing
    background_tasks.add_task(process_analysis, new_request.id)
    
    return {"status": "success", "message": "Videonuz analiz sırasına alındı.", "request_id": new_request.id}

# User Retry Analysis (Ownership check)
@app.post("/dashboard/retry/{analysis_id}")
async def user_retry_analysis(
    analysis_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Lütfen giriş yapın.")

    analysis = db.query(models.AnalysisRequest).filter(
        models.AnalysisRequest.id == analysis_id,
        models.AnalysisRequest.user_id == user.id
    ).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analiz bulunamadı veya yetkiniz yok.")

    # Reset status
    analysis.status = "pending"
    analysis.error_message = None
    db.commit()
    
    # Start Background Processing
    background_tasks.add_task(process_analysis, analysis.id)
    
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/report/download/{analysis_id}")
async def download_report(
    analysis_id: int, 
    format: str = "excel",
    db: Session = Depends(get_db), 
    user: models.User = Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/giris")
    
    report = db.query(models.Report).filter(models.Report.analysis_id == analysis_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Rapor henüz hazır değil veya bulunamadı.")
    
    # Check ownership
    analysis = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == analysis_id).first()
    if not analysis or analysis.user_id != user.id:
        raise HTTPException(status_code=403, detail="Bu rapora erişim yetkiniz yok.")
        
    # Select path based on format
    if format == "pdf":
        relative_path = report.pdf_path.lstrip('/') if report.pdf_path else None
        download_name = f"vidinsight_analiz_{analysis_id}.pdf"
        media_type = 'application/pdf'
    else:
        relative_path = report.excel_path.lstrip('/') if report.excel_path else None
        download_name = f"vidinsight_analiz_{analysis_id}.xlsx"
        media_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

    if not relative_path:
        raise HTTPException(status_code=404, detail=f"İstenen format ({format}) mevcut değil.")

    file_path = BASE_DIR / relative_path
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Dosya sunucuda bulunamadı.")
        
    return FileResponse(
        path=str(file_path), 
        filename=download_name,
        media_type=media_type
    )

# ==================== ADMIN ROUTES ====================
@app.get("/girisburdan", response_class=HTMLResponse)
async def login_page(request: Request):
    if not templates: return HTMLResponse(content="Templates missing", status_code=500)
    try:
        return templates.TemplateResponse(request=request, name="login.html", context={})
    except Exception as e:
        full_error = traceback.format_exc()
        return HTMLResponse(content=f"<pre>{full_error}</pre>", status_code=500)

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
        return templates.TemplateResponse(
            request=request, 
            name="login.html", 
            context={"error": "Geçersiz kullanıcı adı veya şifre!"}
        )

# Admin Dashboard (Restricted)
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")

    if not templates: return HTMLResponse(content="Templates missing", status_code=500)

    try:
        users = db.query(models.User).order_by(models.User.created_at.desc()).all()
        packages = db.query(models.Package).all()
        
        return templates.TemplateResponse(
            request=request, 
            name="admin.html", 
            context={"users": users, "packages": packages}
        )
    except Exception as e:
        full_error = traceback.format_exc()
        print(f"ADMIN DASHBOARD HATASI:\n{full_error}")
        return HTMLResponse(content=f"<h1>Dashboard Hatası</h1><pre>{full_error}</pre>", status_code=500)

# Update User Credits/Package
@app.post("/admin/update_user/{user_id}")
async def admin_update_user(
    request: Request,
    user_id: int, 
    credits: int = Form(...),
    package_id: int = Form(...),
    db: Session = Depends(get_db)
):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401, detail="Yetkisiz erişim.")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user:
        user.credits_remaining = credits
        user.package_id = package_id
        db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

# Global Analyses View
@app.get("/admin/analyses", response_class=HTMLResponse)
async def admin_analyses_page(request: Request, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")
        
    analyses = db.query(models.AnalysisRequest).order_by(models.AnalysisRequest.id.desc()).all()
    return templates.TemplateResponse(
        request=request, 
        name="admin_analyses.html", 
        context={"analyses": analyses}
    )

@app.get("/admin/analysis_error/{analysis_id}")
async def get_analysis_error(analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == analysis_id).first()
    if not analysis:
        return {"error": "Analiz bulunamadı."}
    return {"id": analysis.id, "error": analysis.error_message or "Hata detayı yok."}

# Retry Analysis
@app.post("/admin/retry_analysis/{analysis_id}")
async def retry_analysis(
    request: Request,
    analysis_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401, detail="Yetkisiz erişim.")

    analysis = db.query(models.AnalysisRequest).filter(models.AnalysisRequest.id == analysis_id).first()
    if analysis:
        analysis.status = "pending"
        analysis.error_message = None
        db.commit()
        background_tasks.add_task(process_analysis, analysis.id)
    
    return RedirectResponse(url="/admin/analyses", status_code=status.HTTP_303_SEE_OTHER)

# Toggle Account Status
@app.post("/admin/toggle/{user_id}")
async def toggle_status(request: Request, user_id: int, db: Session = Depends(get_db)):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        return RedirectResponse(url="/girisburdan")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user:
        user.is_active = not user.is_active
        db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

# Admin Logout
@app.get("/cikis")
async def logout(response: Response):
    response = RedirectResponse(url="/girisburdan")
    response.delete_cookie(ADMIN_SESSION_NAME)
    return response

# Manual Add Customer (Admin Only)
@app.post("/admin/add_customer")
async def admin_add_customer(
    request: Request,
    Ad_Soyad: str = Form(...),
    Email: str = Form(...),
    Youtube_Link: str = Form(...),
    paket_adi: str = Form(...),
    Aciklama: str = Form(None),
    db: Session = Depends(get_db)
):
    session = request.cookies.get(ADMIN_SESSION_NAME)
    if session != "authenticated":
        raise HTTPException(status_code=401, detail="Yetkisiz erişim.")

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
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print(f"Error manually adding customer: {e}")
        return HTMLResponse(content=f"Hata: {str(e)}", status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
