import os
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, Session, SQLModel, create_engine
from sqlalchemy import UniqueConstraint, text

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# --- FIX: ROBUST CONNECTION SETTINGS ---
if DATABASE_URL:
    connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
    
    # Add pool_pre_ping=True to automatically reconnect if the DB connection drops
    # Add pool_recycle to proactively recycle connections before the server closes them
    engine = create_engine(
        DATABASE_URL, 
        connect_args=connect_args,
        pool_pre_ping=True, 
        pool_recycle=1800  # Recycle connections every 30 minutes
    )
else:
    if not os.path.exists("data"):
        os.makedirs("data")
    engine = create_engine(
        "sqlite:///data/upasthiti.db", 
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )

class Instructor(SQLModel, table=True):
    username: str = Field(primary_key=True)
    hashed_password: str
    institute_name: str

class Course(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    institute_name: str
    instructor_user: str

class Student(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    institute_name: str = Field(index=True)
    roll_number: str = Field(index=True)
    name: str
    branch: Optional[str] = Field(default=None, index=True)
    face_encoding_json: str
    device_id: Optional[str] = Field(default=None)
    __table_args__ = (UniqueConstraint("institute_name", "roll_number", name="unique_student_roll"),)

class StudentCourseLink(SQLModel, table=True):
    student_id: Optional[int] = Field(default=None, foreign_key="student.id", primary_key=True)
    course_id: Optional[int] = Field(default=None, foreign_key="course.id", primary_key=True)

class ClassSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    instructor_user: str
    institute_name: str
    course_id: int = Field(foreign_key="course.id")
    course_name: str
    batch_name: str
    date_str: str 
    is_active: bool = True

class ActiveQR(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="classsession.id")
    qr_token: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AttendanceLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="classsession.id")
    student_roll: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str
    __table_args__ = (UniqueConstraint("session_id", "student_roll", name="unique_attendance"),)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT device_id FROM student LIMIT 1"))
        except Exception:
            try:
                conn.execute(text("ALTER TABLE student ADD COLUMN device_id VARCHAR"))
                conn.commit()
            except: pass
            
        try:
            conn.execute(text("SELECT branch FROM student LIMIT 1"))
        except Exception:
            try:
                conn.execute(text("ALTER TABLE student ADD COLUMN branch VARCHAR"))
                conn.commit()
            except: pass

def get_session():
    with Session(engine) as session:
        yield session
