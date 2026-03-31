from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100))
    email = Column(String(100), unique=True, index=True)
    hashed_password = Column(String(255))
    phone = Column(String(20), nullable=True)
    company_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Subscription fields
    package_id = Column(Integer, ForeignKey("packages.id"), nullable=True)
    credits_remaining = Column(Integer, default=0)
    renewal_date = Column(DateTime, nullable=True)
    
    package = relationship("Package", back_populates="users")
    analyses = relationship("AnalysisRequest", back_populates="user")

class Package(Base):
    __tablename__ = "packages"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50)) # Tekli, 5'li, 10'lu
    max_videos = Column(Integer)
    price = Column(String(20))
    type = Column(String(20)) # monthly, one-time
    
    users = relationship("User", back_populates="package")

class AnalysisRequest(Base):
    __tablename__ = "analysis_requests"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    video_url = Column(String(255))
    video_id = Column(String(50), nullable=True)
    video_title = Column(String(255), nullable=True)
    status = Column(String(20), default="pending") # pending, processing, completed, error
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="analyses")
    report = relationship("Report", back_populates="analysis", uselist=False)

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analysis_requests.id"))
    pdf_path = Column(String(255), nullable=True)
    excel_path = Column(String(255), nullable=True)
    summary_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    analysis = relationship("AnalysisRequest", back_populates="report")

class Customer(Base):
    """Keep for legacy form submissions from landing page if needed"""
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100))
    email = Column(String(100), index=True)
    youtube_link = Column(String(255))
    package = Column(String(50))
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True)
    password_hash = Column(String(255))
