import cv2
import numpy as np
import face_recognition
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
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Field, Session, SQLModel, create_engine, select, func
from sqlalchemy import UniqueConstraint
from sqlalchemy import text
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel

SECRET_KEY = "upasthiti_secret_key_change_in_production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

class Instructor(SQLModel, table=True):
    username: str = Field(primary_key=True)
    hashed_password: str
    institute_name: str

class StudentCourseLink(SQLModel, table=True):
    student_id: Optional[int] = Field(default=None, foreign_key="student.id", primary_key=True)
    course_id: Optional[int] = Field(default=None, foreign_key="course.id", primary_key=True)

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
    face_encoding_json: str
    device_id: Optional[str] = Field(default=None)

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

if not os.path.exists("data"):
    os.makedirs("data")

sqlite_file_name = "data/upasthiti.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    
    with engine.connect() as conn:
        # 1. Migrate STUDENT table (device_id)
        try:
            conn.execute(text("SELECT device_id FROM student LIMIT 1"))
        except Exception:
            print("⚠️ Migration: Adding 'device_id' to Student table...")
            conn.execute(text("ALTER TABLE student ADD COLUMN device_id VARCHAR"))
            conn.commit()
            print("✅ Student Migration Successful.")

        # 2. Migrate CLASSSESSION table (course_id)
        try:
            conn.execute(text("SELECT course_id FROM classsession LIMIT 1"))
        except Exception:
            print("⚠️ Migration: Adding 'course_id' to ClassSession table...")
            # We add it as INTEGER. 
            # Note: SQLite doesn't easily support adding NOT NULL constraints to existing tables with data
            # so we add it as a nullable integer for now to be safe.
            conn.execute(text("ALTER TABLE classsession ADD COLUMN course_id INTEGER"))
            conn.commit()
            print("✅ ClassSession Migration Successful.")

def get_session():
    with Session(engine) as session:
        yield session

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
    height, width = img.shape[:2]
    max_width = 600
    if width > max_width:
        scaling_factor = max_width / float(width)
        new_height = int(height * scaling_factor)
        img = cv2.resize(img, (max_width, new_height))

    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    encodings = face_recognition.face_encodings(rgb_img)
    if len(encodings) > 0:
        return encodings[0].tolist()
    return None

def crop_face(img):
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_img)

    if len(face_locations) == 0:
        return None, "No face detected"

    face_loc = max(face_locations, key=lambda f: (f[2] - f[0]) * (f[1] - f[3]))
    top, right, bottom, left = face_loc

    height, width, _ = img.shape
    pad_h = int((bottom - top) * 0.2)
    pad_w = int((right - left) * 0.2)

    new_top = max(0, top - pad_h)
    new_bottom = min(height, bottom + pad_h)
    new_left = max(0, left - pad_w)
    new_right = min(width, right + pad_w)

    cropped_face = img[new_top:new_bottom, new_left:new_right]
    cropped_face = cv2.resize(cropped_face, (400, 400))

    return cropped_face, "Success"

def validate_liveness(img):
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="Upasthiti API", lifespan=lifespan)

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

# --- DASHBOARD STATS (FIXED) ---
@app.get("/api/dashboard_stats")
async def get_stats(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    # 1. Count Total Students
    total_students = session.exec(select(func.count(Student.id)).where(Student.institute_name == user.institute_name)).one()
    
    # 2. Get All Courses
    courses = session.exec(select(Course).where(Course.institute_name == user.institute_name)).all()
    course_names = [c.name for c in courses]

    # 3. FIX: Return total 'len(courses)' instead of 'active_sessions'
    return {
        "institute": user.institute_name,
        "total_students": total_students,
        "active_courses": len(courses), # <--- Changed this to show Total Courses
        "course_list": course_names
    }

class StudentRegisterRequest(BaseModel):
    rollNumber: str
    name: str
    photoBase64: str
    course_id: int 

@app.post("/api/register")
async def register_student(body: StudentRegisterRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    student = session.exec(select(Student).where(Student.roll_number == body.rollNumber, Student.institute_name == user.institute_name)).first()
    
    if not student:
        img_bytes = decode_base64(body.photoBase64)
        img = decode_image_bytes(img_bytes)
        if img is None: raise HTTPException(400, "Invalid Image")

        cropped_img, msg = crop_face(img)
        if cropped_img is None: raise HTTPException(400, f"Registration Failed: {msg}")

        encoding = get_encoding_from_image(cropped_img)
        if not encoding: raise HTTPException(400, "No face found")
        
        student = Student(
            institute_name=user.institute_name,
            roll_number=body.rollNumber,
            name=body.name,
            face_encoding_json=json.dumps(encoding)
        )
        session.add(student)
        session.commit()
        session.refresh(student)

    link = session.exec(select(StudentCourseLink).where(
        StudentCourseLink.student_id == student.id, 
        StudentCourseLink.course_id == body.course_id
    )).first()

    if not link:
        new_link = StudentCourseLink(student_id=student.id, course_id=body.course_id)
        session.add(new_link)
        session.commit()

    return {"success": True, "message": "Student Registered & Linked to Course"}

@app.post("/api/bulk_register")
async def bulk_register(course_id: int, file: UploadFile = File(...), user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course or course.institute_name != user.institute_name:
        raise HTTPException(403, "Invalid Course")

    contents = await file.read()
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except:
        raise HTTPException(400, "Invalid file format")

    success_count = 0
    errors = []

    for _, row in df.iterrows():
        try:
            roll = str(row['roll_no']).strip()
            name = str(row['name']).strip()
            link_url = str(row['image_link']).strip()
        except:
            continue

        student = session.exec(select(Student).where(Student.roll_number == roll, Student.institute_name == user.institute_name)).first()
        
        if not student:
            try:
                response = requests.get(link_url, timeout=10)
                if response.status_code == 200:
                    img = decode_image_bytes(response.content)
                    if img is None: continue

                    cropped_img, _ = crop_face(img)
                    if cropped_img is None: cropped_img = img 
                    
                    encoding = get_encoding_from_image(cropped_img)
                    if encoding:
                        student = Student(
                            institute_name=user.institute_name,
                            roll_number=roll,
                            name=name,
                            face_encoding_json=json.dumps(encoding)
                        )
                        session.add(student)
                        session.commit()
                        session.refresh(student)
                    else:
                        errors.append(f"{roll}: No face found")
                        continue
                else:
                    errors.append(f"{roll}: Image download failed")
                    continue
            except:
                errors.append(f"{roll}: Network Error")
                continue

        if student:
            link = session.exec(select(StudentCourseLink).where(StudentCourseLink.student_id == student.id, StudentCourseLink.course_id == course_id)).first()
            if not link:
                session.add(StudentCourseLink(student_id=student.id, course_id=course_id))
                success_count += 1

    session.commit()
    return {"success": True, "added": success_count, "errors": errors}

class CreateSessionRequest(BaseModel):
    course_id: int 
    course_name: str
    batch_name: str
    date_str: str

@app.post("/api/start_class")
async def start_class(body: CreateSessionRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    course = session.get(Course, body.course_id)
    if not course or course.institute_name != user.institute_name:
        raise HTTPException(400, "Invalid Course ID")

    existing = session.exec(select(ClassSession).where(ClassSession.instructor_user == user.username, ClassSession.is_active == True)).all()
    for s in existing:
        s.is_active = False
        session.add(s)
    
    new_session = ClassSession(
        instructor_user=user.username,
        institute_name=user.institute_name,
        course_id=body.course_id,
        course_name=course.name,
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

    # 1. Generate new Token
    token_str = str(uuid.uuid4())
    qr_entry = ActiveQR(session_id=active_session.id, qr_token=token_str, created_at=datetime.now(timezone.utc))
    session.add(qr_entry)
    
    # 2. NEW: Count present students for this session
    present_count = session.exec(select(func.count(AttendanceLog.id)).where(AttendanceLog.session_id == active_session.id)).one()
    
    session.commit()
    
    # 3. Return both Token AND Count
    return {"qrToken": token_str, "student_count": present_count}

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
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return StreamingResponse(output, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.get("/api/download_course_report/{course_id}")
async def download_course_report(course_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course or course.institute_name != user.institute_name:
        raise HTTPException(403, "Access Denied")

    links = session.exec(select(StudentCourseLink).where(StudentCourseLink.course_id == course_id)).all()
    student_ids = [l.student_id for l in links]
    
    if not student_ids:
        raise HTTPException(400, "No students enrolled in this course")

    students = session.exec(select(Student).where(Student.id.in_(student_ids))).all()
    student_map = {s.roll_number: s.name for s in students}
    all_rolls = list(student_map.keys())

    sessions = session.exec(select(ClassSession).where(
        ClassSession.course_id == course_id
    ).order_by(ClassSession.date_str)).all()
    
    if not sessions:
        raise HTTPException(400, "No classes conducted yet")

    session_map = {s.id: s.date_str[:10] for s in sessions}
    session_ids = list(session_map.keys())

    logs = session.exec(select(AttendanceLog).where(AttendanceLog.session_id.in_(session_ids))).all()

    data = []
    attendance_lookup = set((log.student_roll, log.session_id) for log in logs)

    for roll in all_rolls:
        row = {
            "Roll Number": roll,
            "Name": student_map.get(roll, "Unknown")
        }
        
        for sess in sessions:
            date_col = f"{sess.date_str[:10]} ({sess.batch_name})"
            if (roll, sess.id) in attendance_lookup:
                row[date_col] = "P"
            else:
                row[date_col] = "A"
        
        data.append(row)

    df = pd.DataFrame(data)
    cols = ["Roll Number", "Name"] + [c for c in df.columns if c not in ["Roll Number", "Name"]]
    df = df[cols]

    filename = f"Master_Attendance_{course.name}.xlsx"
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Attendance")
    output.seek(0)

    return StreamingResponse(output, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={"Content-Disposition": f"attachment; filename={filename}"})

class CourseCreate(BaseModel):
    name: str

@app.post("/api/courses")
async def create_course(body: CourseCreate, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    new_course = Course(name=body.name, institute_name=user.institute_name, instructor_user=user.username)
    session.add(new_course)
    session.commit()
    return {"success": True, "id": new_course.id, "name": new_course.name}

@app.get("/api/courses")
async def get_courses(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    return session.exec(select(Course).where(Course.institute_name == user.institute_name)).all()

@app.delete("/api/courses/{course_id}")
async def delete_course(course_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course or course.institute_name != user.institute_name:
        raise HTTPException(403, "Not Authorized")
    
    links = session.exec(select(StudentCourseLink).where(StudentCourseLink.course_id == course_id)).all()
    for link in links:
        session.delete(link)
        
    session.delete(course)
    session.commit()
    return {"success": True}

@app.get("/api/students")
async def get_students(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    students = session.exec(select(Student).where(Student.institute_name == user.institute_name)).all()
    return [{"id": s.id, "roll_number": s.roll_number, "name": s.name} for s in students]

@app.delete("/api/students/{student_id}")
async def delete_student(student_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    student = session.get(Student, student_id)
    if not student or student.institute_name != user.institute_name:
        raise HTTPException(403, "Not Authorized")
    
    links = session.exec(select(StudentCourseLink).where(StudentCourseLink.student_id == student_id)).all()
    for link in links:
        session.delete(link)

    session.delete(student)
    session.commit()
    return {"success": True}

class AttendanceRequest(BaseModel):
    rollNumber: str
    qrCodeData: str
    photoBase64: str
    timestamp: str 

@app.post("/api/attendance")
async def mark_attendance(body: AttendanceRequest, session: Session = Depends(get_session)):
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

    statement = select(ActiveQR).where(ActiveQR.qr_token == body.qrCodeData)
    qr_entry = session.exec(statement).first()
    if not qr_entry:
        raise HTTPException(status_code=404, detail="Invalid QR Code")

    qr_created_at = qr_entry.created_at.replace(tzinfo=timezone.utc)
    server_now = datetime.now(timezone.utc)
    qr_age = (server_now - qr_created_at).total_seconds()
    
    if qr_age > 20:
        raise HTTPException(status_code=400, detail="QR Code Expired. Scan the new one.")

    img_bytes = decode_base64(body.photoBase64)
    img = decode_image_bytes(img_bytes)
    if img is None: 
        raise HTTPException(status_code=400, detail="Invalid image")

    is_live, reason = validate_liveness(img)
    if not is_live:
        raise HTTPException(status_code=400, detail=f"Liveness Check Failed: {reason}")

    class_session = session.get(ClassSession, qr_entry.session_id)
    if not class_session or not class_session.is_active:
        raise HTTPException(status_code=400, detail="Class Session has ended")

    student = session.exec(select(Student).where(
        Student.roll_number == body.rollNumber, 
        Student.institute_name == class_session.institute_name
    )).first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student {body.rollNumber} not found")

    is_enrolled = session.exec(select(StudentCourseLink).where(
        StudentCourseLink.student_id == student.id,
        StudentCourseLink.course_id == class_session.course_id
    )).first()

    if not is_enrolled:
        raise HTTPException(status_code=403, detail="Student is not enrolled in this course")

    live_encoding = get_encoding_from_image(img)
    if not live_encoding: 
        raise HTTPException(status_code=400, detail="No face detected")
    
    stored_encoding = np.array(json.loads(student.face_encoding_json))
    match = face_recognition.compare_faces([stored_encoding], np.array(live_encoding), tolerance=0.5)
    if not match[0]: 
        raise HTTPException(status_code=401, detail="Face Mismatch: Verification Failed")

    existing = session.exec(select(AttendanceLog).where(
        AttendanceLog.session_id == class_session.id, 
        AttendanceLog.student_roll == body.rollNumber
    )).first()
    
    if existing: 
        return {"success": True, "message": "Attendance already marked."}

    try:
        new_log = AttendanceLog(
            session_id=class_session.id, 
            student_roll=body.rollNumber, 
            timestamp=datetime.now(timezone.utc), 
            status="PRESENT"
        )
        session.add(new_log)
        session.commit()
    except Exception:
        session.rollback()
        return {"success": True, "message": "Attendance already marked."}
    
    return {"success": True, "message": "Attendance Marked Successfully"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/icon.png")

@app.get("/student")
async def student_ui():
    return FileResponse("static/student.html")

app.mount("/static", StaticFiles(directory="static"), name="static_assets")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
