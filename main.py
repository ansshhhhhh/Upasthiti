import cv2
import numpy as np
import face_recognition
import base64
import json
import pandas as pd
import uuid
import requests
import io
from datetime import datetime, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Field, Session, SQLModel, create_engine, select, func
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel

# --- CONFIGURATION ---
SECRET_KEY = "upasthiti_secret_key_change_in_production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

# --- DATABASE MODELS ---

class Instructor(SQLModel, table=True):
    username: str = Field(primary_key=True)
    hashed_password: str
    institute_name: str  # Links instructor to an institute

class Student(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    institute_name: str = Field(index=True) # Student belongs to this institute
    roll_number: str = Field(index=True)
    name: str
    face_encoding_json: str 

class ClassSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    instructor_user: str
    institute_name: str # Session belongs to this institute
    course_name: str
    batch_name: str
    date_str: str 
    is_active: bool = True

class ActiveQR(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="classsession.id")
    qr_token: str
    created_at: datetime

class AttendanceLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="classsession.id")
    student_roll: str
    timestamp: datetime
    status: str

# --- DB SETUP ---
sqlite_file_name = "upasthiti.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

# --- SECURITY UTILS ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = session.get(Instructor, username)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# --- HELPER: IMAGE PROCESSING ---
def decode_image_bytes(image_data):
    try:
        nparr = np.frombuffer(image_data, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except:
        return None

def decode_base64(base64_string: str):
    if "," in base64_string:
        base64_string = base64_string.split(",")[1]
    return base64.b64decode(base64_string)

def get_encoding_from_image(img):
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    encodings = face_recognition.face_encodings(rgb_img)
    if len(encodings) > 0:
        return encodings[0].tolist()
    return None

# --- APP LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="Upasthiti API", lifespan=lifespan)

# --- AUTH ROUTES ---

class InstructorRegister(BaseModel):
    username: str
    password: str
    institute_name: str

@app.post("/api/instructor/register")
async def register_instructor(body: InstructorRegister, session: Session = Depends(get_session)):
    if session.get(Instructor, body.username):
        raise HTTPException(400, "Username taken")
    
    new_user = Instructor(
        username=body.username,
        hashed_password=get_password_hash(body.password),
        institute_name=body.institute_name
    )
    session.add(new_user)
    session.commit()
    return {"success": True, "message": "Instructor registered successfully"}

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    user = session.get(Instructor, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    # Store institute in token for easy access logic? Or just username.
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "institute": user.institute_name}

# --- DASHBOARD STATS ---
@app.get("/api/dashboard_stats")
async def get_stats(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    # Only count students from YOUR institute
    total_students = session.exec(select(func.count(Student.id)).where(Student.institute_name == user.institute_name)).one()
    
    # Only your courses
    courses = session.exec(select(ClassSession.course_name).where(ClassSession.institute_name == user.institute_name).distinct()).all()
    
    return {
        "institute": user.institute_name,
        "total_students": total_students,
        "active_courses": len(courses),
        "course_list": courses
    }

# --- ADD STUDENT ---
class StudentRegisterRequest(BaseModel):
    rollNumber: str
    name: str
    photoBase64: str

@app.post("/api/register")
async def register_student(body: StudentRegisterRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    # Check existing in THIS institute
    existing = session.exec(select(Student).where(Student.roll_number == body.rollNumber, Student.institute_name == user.institute_name)).first()
    if existing:
        raise HTTPException(400, "Student already registered in this institute")

    img_bytes = decode_base64(body.photoBase64)
    img = decode_image_bytes(img_bytes)
    if img is None:
        raise HTTPException(400, "Invalid Image")

    encoding = get_encoding_from_image(img)
    if not encoding:
        raise HTTPException(400, "No face found in photo")
    
    new_student = Student(
        institute_name=user.institute_name, # Auto-assign Instructor's Institute
        roll_number=body.rollNumber,
        name=body.name,
        face_encoding_json=json.dumps(encoding)
    )
    session.add(new_student)
    session.commit()
    return {"success": True, "message": "Student Added"}

@app.post("/api/bulk_register")
async def bulk_register(file: UploadFile = File(...), user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    contents = await file.read()
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except:
        raise HTTPException(400, "Invalid file format")

    errors = []
    success_count = 0
    
    for _, row in df.iterrows():
        roll = str(row['roll_no']).strip()
        name = str(row['name']).strip()
        link = str(row['image_link']).strip()

        if session.exec(select(Student).where(Student.roll_number == roll, Student.institute_name == user.institute_name)).first():
            continue

        try:
            response = requests.get(link, timeout=10)
            if response.status_code == 200:
                img = decode_image_bytes(response.content)
                encoding = get_encoding_from_image(img)
                if encoding:
                    session.add(Student(
                        institute_name=user.institute_name,
                        roll_number=roll,
                        name=name,
                        face_encoding_json=json.dumps(encoding)
                    ))
                    success_count += 1
                else:
                    errors.append(f"{roll}: No face found")
            else:
                errors.append(f"{roll}: Image download failed")
        except:
            errors.append(f"{roll}: Error")

    session.commit()
    return {"success": True, "added": success_count, "errors": errors}

# --- CLASS SESSION ---
class CreateSessionRequest(BaseModel):
    course_name: str
    batch_name: str
    date_str: str

@app.post("/api/start_class")
async def start_class(body: CreateSessionRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    # Deactivate old sessions for this instructor
    existing = session.exec(select(ClassSession).where(ClassSession.instructor_user == user.username, ClassSession.is_active == True)).all()
    for s in existing:
        s.is_active = False
        session.add(s)
    
    new_session = ClassSession(
        instructor_user=user.username,
        institute_name=user.institute_name,
        course_name=body.course_name,
        batch_name=body.batch_name,
        date_str=body.date_str,
        is_active=True
    )
    session.add(new_session)
    session.commit()
    return {"success": True, "session_id": new_session.id}

@app.get("/api/get_qr")
async def get_qr(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    active_session = session.exec(select(ClassSession).where(ClassSession.instructor_user == user.username, ClassSession.is_active == True)).first()
    if not active_session:
        raise HTTPException(400, "No active class")

    token_str = str(uuid.uuid4())
    qr_entry = ActiveQR(session_id=active_session.id, qr_token=token_str, created_at=datetime.utcnow())
    session.add(qr_entry)
    session.commit()
    return {"qrToken": token_str}

@app.get("/api/download_excel/{session_id}")
async def download_excel(session_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    class_session = session.get(ClassSession, session_id)
    if not class_session or class_session.institute_name != user.institute_name:
        raise HTTPException(403, "Access Denied")
    
    logs = session.exec(select(AttendanceLog).where(AttendanceLog.session_id == session_id)).all()
    data = []
    for log in logs:
        student = session.exec(select(Student).where(Student.roll_number == log.student_roll, Student.institute_name == user.institute_name)).first()
        name = student.name if student else "Unknown"
        data.append({"Roll Number": log.student_roll, "Name": name, "Time": log.timestamp.strftime("%H:%M:%S"), "Status": log.status})
    
    df = pd.DataFrame(data, columns=["Roll Number", "Name", "Time", "Status"])
    filename = f"Attendance_{class_session.course_name}_{class_session.batch_name}.xlsx"
    df.to_excel(filename, index=False)
    return FileResponse(path=filename, filename=filename, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# --- MOBILE APP ENDPOINT ---
class AttendanceRequest(BaseModel):
    rollNumber: str
    qrCodeData: str
    photoBase64: str

@app.post("/api/attendance")
async def mark_attendance(body: AttendanceRequest, session: Session = Depends(get_session)):
    # 1. Validate QR
    statement = select(ActiveQR).where(ActiveQR.qr_token == body.qrCodeData)
    qr_entry = session.exec(statement).first()
    if not qr_entry or (datetime.utcnow() - qr_entry.created_at).total_seconds() > 15: # 15s buffer
        raise HTTPException(403, "Invalid or Expired QR")

    class_session = session.get(ClassSession, qr_entry.session_id)
    if not class_session or not class_session.is_active:
        raise HTTPException(403, "Class Ended")

    # 2. Find Student (MUST be in same institute as Class Session)
    student = session.exec(select(Student).where(
        Student.roll_number == body.rollNumber, 
        Student.institute_name == class_session.institute_name
    )).first()
    
    if not student:
        raise HTTPException(404, "Student not found in this Institute")

    # 3. Face Match
    img_bytes = decode_base64(body.photoBase64)
    img = decode_image_bytes(img_bytes)
    if img is None: raise HTTPException(400, "Bad Image")
    
    live_encoding = get_encoding_from_image(img)
    if not live_encoding: raise HTTPException(400, "No face visible")
    
    stored_encoding = np.array(json.loads(student.face_encoding_json))
    match = face_recognition.compare_faces([stored_encoding], np.array(live_encoding), tolerance=0.5)
    
    if not match[0]: raise HTTPException(401, "Face mismatch")

    # 4. Mark
    existing = session.exec(select(AttendanceLog).where(AttendanceLog.session_id == class_session.id, AttendanceLog.student_roll == body.rollNumber)).first()
    if existing: return {"success": True, "message": "Already Marked"}

    new_log = AttendanceLog(session_id=class_session.id, student_roll=body.rollNumber, timestamp=datetime.utcnow(), status="PRESENT")
    session.add(new_log)
    session.commit()
    return {"success": True, "message": "Marked Present"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
