import cv2
import numpy as np
# REMOVED: import face_recognition
from deepface import DeepFace # ADDED: DeepFace replacement
import base64
import json
import pandas as pd
import uuid
import requests
import io
import os
from datetime import datetime, timedelta, timezone
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
SECRET_KEY = os.getenv("SECRET_KEY", "upasthiti_secret_key_change_in_production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

# --- DATABASE MODELS ---
class Instructor(SQLModel, table=True):
    username: str = Field(primary_key=True)
    hashed_password: str
    institute_name: str

class Student(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    institute_name: str = Field(index=True)
    roll_number: str = Field(index=True)
    name: str
    face_encoding_json: str 

class ClassSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    instructor_user: str
    institute_name: str
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

# --- DB SETUP (Docker Friendly) ---
if not os.path.exists("data"):
    os.makedirs("data")

sqlite_file_name = "data/upasthiti.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

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
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
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

# --- HELPER: IMAGE PROCESSING & ANTI-SPOOFING ---

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

# UPDATE THIS FUNCTION
def get_encoding_from_image(img):
    try:
        # CHANGED: 'Facenet' -> 'SFace' (Lightweight standard)
        embedding_obj = DeepFace.represent(img_path=img, model_name="SFace", enforce_detection=False)
        return embedding_obj[0]["embedding"]
    except Exception as e:
        print(f"DeepFace Error: {e}")
        return None



def validate_liveness(img):
    """
    Checks if the image is likely a real face or a screen/photo spoof.
    Returns: (is_live: bool, reason: str)
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    
    if blur_score < 50: 
        return False, "Image too blurry/flat (Possible Screen Spoof)"

    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    bright_pixels = sum(hist[250:]) 
    total_pixels = img.shape[0] * img.shape[1]
    bright_ratio = bright_pixels / total_pixels

    if bright_ratio > 0.05:
        return False, "Excessive Glare (Possible Screen Reflection)"
        
    dark_pixels = sum(hist[:10])
    dark_ratio = dark_pixels / total_pixels
    if dark_ratio > 0.6:
        return False, "Image too dark for verification"

    return True, "Live"

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
    
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "institute": user.institute_name}

# --- DASHBOARD STATS ---
@app.get("/api/dashboard_stats")
async def get_stats(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    total_students = session.exec(select(func.count(Student.id)).where(Student.institute_name == user.institute_name)).one()
    courses = session.exec(select(ClassSession.course_name).where(ClassSession.institute_name == user.institute_name).distinct()).all()
    active_sessions = session.exec(select(func.count(ClassSession.id)).where(ClassSession.institute_name == user.institute_name, ClassSession.is_active == True)).one()

    return {
        "institute": user.institute_name,
        "total_students": total_students,
        "active_courses": active_sessions,
        "course_list": courses
    }

# --- ADD STUDENT ---
class StudentRegisterRequest(BaseModel):
    rollNumber: str
    name: str
    photoBase64: str

@app.post("/api/register")
async def register_student(body: StudentRegisterRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    existing = session.exec(select(Student).where(Student.roll_number == body.rollNumber, Student.institute_name == user.institute_name)).first()
    if existing:
        raise HTTPException(400, "Student already registered in this institute")

    img_bytes = decode_base64(body.photoBase64)
    img = decode_image_bytes(img_bytes)
    if img is None:
        raise HTTPException(400, "Invalid Image")

    # Use DeepFace Embedding
    encoding = get_encoding_from_image(img)
    if not encoding:
        raise HTTPException(400, "No face found in photo")
    
    new_student = Student(
        institute_name=user.institute_name,
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
                encoding = get_encoding_from_image(img) # Uses DeepFace now
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

@app.post("/api/end_class")
async def end_class(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    active_session = session.exec(select(ClassSession).where(ClassSession.instructor_user == user.username, ClassSession.is_active == True)).first()
    if active_session:
        active_session.is_active = False
        session.add(active_session)
        session.commit()
        return {"success": True, "message": "Class ended successfully"}
    return {"success": False, "message": "No active class found"}

@app.get("/api/get_qr")
async def get_qr(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    active_session = session.exec(select(ClassSession).where(ClassSession.instructor_user == user.username, ClassSession.is_active == True)).first()
    if not active_session:
        raise HTTPException(400, "No active class")

    token_str = str(uuid.uuid4())
    qr_entry = ActiveQR(session_id=active_session.id, qr_token=token_str, created_at=datetime.now(timezone.utc))
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
    
    ist = timezone(timedelta(hours=5, minutes=30))

    for log in logs:
        student = session.exec(select(Student).where(Student.roll_number == log.student_roll, Student.institute_name == user.institute_name)).first()
        name = student.name if student else "Unknown"
        
        local_time_obj = log.timestamp.astimezone(ist)
        local_time_str = local_time_obj.strftime("%H:%M:%S")
        
        data.append({"Roll Number": log.student_roll, "Name": name, "Time": local_time_str, "Status": log.status})
    
    df = pd.DataFrame(data, columns=["Roll Number", "Name", "Time", "Status"])
    filename = f"Attendance_{class_session.course_name}_{class_session.batch_name}.xlsx"
    df.to_excel(filename, index=False)
    return FileResponse(path=filename, filename=filename, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# --- MOBILE APP ENDPOINT ---

class AttendanceRequest(BaseModel):
    rollNumber: str
    qrCodeData: str
    photoBase64: str
    timestamp: str 

@app.post("/api/attendance")
async def mark_attendance(body: AttendanceRequest, session: Session = Depends(get_session)):
    
    # 1. PARSE TIMESTAMPS
    try:
        clean_ts = body.timestamp.replace("Z", "")
        client_time = datetime.fromisoformat(clean_ts)
        if client_time.tzinfo is None:
            ist_offset = timezone(timedelta(hours=5, minutes=30))
            client_time = client_time.replace(tzinfo=ist_offset)
            client_time = client_time.astimezone(timezone.utc)
        else:
            client_time = client_time.astimezone(timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")

    # 2. VERIFY QR
    statement = select(ActiveQR).where(ActiveQR.qr_token == body.qrCodeData)
    qr_entry = session.exec(statement).first()
    if not qr_entry:
        raise HTTPException(status_code=404, detail="Invalid QR Code")

    # 3. SYNC CHECK
    qr_time = qr_entry.created_at.replace(tzinfo=timezone.utc)
    time_diff = (client_time - qr_time).total_seconds()
    if not (-60 <= time_diff <= 60):
        raise HTTPException(status_code=400, detail=f"Timing Mismatch: Diff is {time_diff:.1f}s")

    # 4. DECODE IMAGE
    img_bytes = decode_base64(body.photoBase64)
    img = decode_image_bytes(img_bytes)
    if img is None: 
        raise HTTPException(status_code=400, detail="Invalid image")

    # 5. ANTI-SPOOFING (LIVENESS) CHECK
    is_live, reason = validate_liveness(img)
    if not is_live:
        raise HTTPException(status_code=400, detail=f"Liveness Check Failed: {reason}")

    # 6. FACE MATCH
    class_session = session.get(ClassSession, qr_entry.session_id)
    if not class_session or not class_session.is_active:
        raise HTTPException(status_code=400, detail="Class Session has ended")

    student = session.exec(select(Student).where(
        Student.roll_number == body.rollNumber, 
        Student.institute_name == class_session.institute_name
    )).first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student {body.rollNumber} not found")

    
    try:
        # CHANGED: 'Facenet' -> 'SFace'
        live_embedding = DeepFace.represent(img_path=img, model_name="SFace", enforce_detection=False)[0]["embedding"]
        
        # 2. Retrieve stored embedding (JSON -> List)
        stored_embedding = json.loads(student.face_encoding_json)

        # 3. Calculate Cosine Similarity
        # A match is usually found if cosine distance < 0.40 (for VGG-Face)
        # Cosine Distance = 1 - Cosine Similarity
        
        a = np.array(live_embedding)
        b = np.array(stored_embedding)
        
        # Manual Cosine Distance Calculation
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        cosine_similarity = dot_product / (norm_a * norm_b)
        cosine_distance = 1 - cosine_similarity

        if cosine_distance > 0.593:
             raise HTTPException(status_code=401, detail="Face Mismatch: Verification Failed")

    except Exception as e:
        # If the student was registered with the OLD system (dlib 128-d), this math will crash.
        # We catch that here.
        print(f"DeepFace Match Error: {e}")
        raise HTTPException(status_code=500, detail="Error verifying face (Student may need to re-register)")

    # 7. MARK ATTENDANCE
    existing = session.exec(select(AttendanceLog).where(
        AttendanceLog.session_id == class_session.id, 
        AttendanceLog.student_roll == body.rollNumber
    )).first()
    
    if existing: 
        return {"success": True, "message": "Attendance already marked."}

    new_log = AttendanceLog(
        session_id=class_session.id, 
        student_roll=body.rollNumber, 
        timestamp=datetime.now(timezone.utc), 
        status="PRESENT"
    )
    session.add(new_log)
    session.commit()
    
    return {"success": True, "message": "Attendance Marked Successfully"}

# Serve static files if folder exists
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
