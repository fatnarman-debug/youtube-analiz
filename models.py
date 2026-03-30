from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from database import Base
import datetime

class Customer(Base):
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
