from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True)
    email = Column(String(100), unique=True, index=True)
    password_hash = Column(String(255))
    full_name = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Credit & Subscription System
    credits = Column(Integer, default=1)  # Başlangıçta 1 ücretsiz hak
    subscription_plan = Column(String(50), default="free")  # free, single, creator, agency
    last_renewal_date = Column(DateTime, default=datetime.datetime.utcnow)
    
    analyses = relationship("AnalysisRequest", back_populates="user")

class AnalysisRequest(Base):
    __tablename__ = "analysis_requests"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    video_url = Column(String(255))
    video_title = Column(String(255), default="İşleniyor...")
    status = Column(String(20), default="pending") # pending, completed
    report_file_name = Column(String(255), nullable=True) # Adminin yüklediği dosya adı
    admin_note = Column(String(2000), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="analyses")

class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True)
    password_hash = Column(String(255))

class BlogPost(Base):
    __tablename__ = "blog_posts"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255))
    slug = Column(String(255), unique=True, index=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_published = Column(Boolean, default=True)
