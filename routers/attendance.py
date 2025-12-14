import asyncio
from datetime import datetime, timedelta, timezone
import uuid
import json
import re
import io
import numpy as np
import face_recognition
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select, func

from database import get_session, engine, ClassSession, ActiveQR, AttendanceLog, Student, StudentCourseLink, Course, Instructor
from auth import get_current_user
from schemas import CreateSessionRequest, AttendanceRequest
from utils import decode_base64, decode_image_bytes, validate_liveness, get_encoding_from_image

router = APIRouter()

async def delayed_qr_cleanup(session_id: int):
    await asyncio.sleep(10)
    with Session(engine) as session:
        statement = select(ActiveQR).where(ActiveQR.session_id == session_id)
        results = session.exec(statement).all()
        for row in results:
            session.delete(row)
        session.commit()

@router.post("/api/start_class")
async def start_class(body: CreateSessionRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    course = session.get(Course, body.course_id)
    if not course or course.instructor_user != user.username:
        raise HTTPException(400, "Invalid Course ID")
    
    existing = session.exec(select(ClassSession).where(ClassSession.instructor_user == user.username, ClassSession.is_active == True)).all()
    for s in existing:
        s.is_active = False
        session.add(s)
    
    new_session = ClassSession(instructor_user=user.username, institute_name=user.institute_name, course_id=body.course_id, course_name=course.name, batch_name=body.batch_name, date_str=body.date_str, is_active=True)
    session.add(new_session)
    session.commit()
    return {"success": True, "session_id": new_session.id}

@router.post("/api/end_class")
async def end_class(background_tasks: BackgroundTasks, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    active_session = session.exec(select(ClassSession).where(ClassSession.instructor_user == user.username, ClassSession.is_active == True)).first()
    if active_session:
        active_session.is_active = False
        session.add(active_session)
        session.commit()
        background_tasks.add_task(delayed_qr_cleanup, active_session.id)
        return {"success": True, "message": "Class ended successfully"}
    return {"success": False, "message": "No active class found"}

@router.get("/api/get_qr")
async def get_qr(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    active_session = session.exec(select(ClassSession).where(ClassSession.instructor_user == user.username, ClassSession.is_active == True)).first()
    if not active_session: raise HTTPException(400, "No active class")
    
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
        old_qrs = session.exec(select(ActiveQR).where(ActiveQR.session_id == active_session.id, ActiveQR.created_at < cutoff)).all()
        for qr in old_qrs: session.delete(qr)
    except: pass 

    token_str = str(uuid.uuid4())
    qr_entry = ActiveQR(session_id=active_session.id, qr_token=token_str, created_at=datetime.now(timezone.utc))
    session.add(qr_entry)
    present_count = session.exec(select(func.count(AttendanceLog.id)).where(AttendanceLog.session_id == active_session.id)).one()
    session.commit()
    return {"qrToken": token_str, "student_count": present_count}

@router.post("/api/attendance")
async def mark_attendance(body: AttendanceRequest, session: Session = Depends(get_session)):
    try:
        clean_ts = body.timestamp.replace("Z", "")
        client_time = datetime.fromisoformat(clean_ts)
        if client_time.tzinfo is None:
            client_time = client_time.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        client_time = client_time.astimezone(timezone.utc)
    except ValueError: raise HTTPException(status_code=400, detail="Invalid timestamp format")

    statement = select(ActiveQR).where(ActiveQR.qr_token == body.qrCodeData)
    qr_entry = session.exec(statement).first()
    if not qr_entry: raise HTTPException(status_code=404, detail="Invalid QR Code")
    
    qr_created_at = qr_entry.created_at
    if qr_created_at.tzinfo is None: qr_created_at = qr_created_at.replace(tzinfo=timezone.utc)
        
    server_now = datetime.now(timezone.utc)
    if (server_now - qr_created_at).total_seconds() > 20:
        raise HTTPException(status_code=400, detail="QR Code Expired. Scan the new one.")

    img_bytes = decode_base64(body.photoBase64)
    img = decode_image_bytes(img_bytes)
    if img is None: raise HTTPException(status_code=400, detail="Invalid image")
    is_live, reason = validate_liveness(img)
    if not is_live: raise HTTPException(status_code=400, detail=f"Liveness Check Failed: {reason}")

    class_session = session.get(ClassSession, qr_entry.session_id)
    if not class_session or not class_session.is_active: raise HTTPException(status_code=400, detail="Class Session has ended")
    if body.instituteName != class_session.institute_name: raise HTTPException(status_code=403, detail="Institute name mismatch")

    student = session.exec(select(Student).where(Student.roll_number == body.rollNumber, Student.institute_name == body.instituteName)).first()
    if not student: raise HTTPException(status_code=404, detail=f"Student {body.rollNumber} not found")

    is_enrolled = session.exec(select(StudentCourseLink).where(StudentCourseLink.student_id == student.id, StudentCourseLink.course_id == class_session.course_id)).first()
    if not is_enrolled: raise HTTPException(status_code=403, detail="Student is not enrolled in this course")

    live_encoding = get_encoding_from_image(img)
    if not live_encoding: raise HTTPException(status_code=400, detail="No face detected")
    stored_encoding = np.array(json.loads(student.face_encoding_json))
    match = face_recognition.compare_faces([stored_encoding], np.array(live_encoding), tolerance=0.5)
    if not match[0]: raise HTTPException(status_code=401, detail="Face Mismatch: Verification Failed")

    existing = session.exec(select(AttendanceLog).where(AttendanceLog.session_id == class_session.id, AttendanceLog.student_roll == body.rollNumber)).first()
    if existing: return {"success": True, "message": "Attendance already marked."}
    
    try:
        new_log = AttendanceLog(session_id=class_session.id, student_roll=body.rollNumber, timestamp=datetime.now(timezone.utc), status="PRESENT")
        session.add(new_log)
        session.commit()
    except:
        session.rollback()
        return {"success": True, "message": "Attendance already marked."}
    return {"success": True, "message": "Attendance Marked Successfully"}

@router.get("/api/download_excel/{session_id}")
async def download_excel(session_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    class_session = session.get(ClassSession, session_id)
    if not class_session or class_session.instructor_user != user.username:
        raise HTTPException(403, "Access Denied")
    
    logs = session.exec(select(AttendanceLog).where(AttendanceLog.session_id == session_id)).all()
    data = []
    ist = timezone(timedelta(hours=5, minutes=30))
    for log in logs:
        student = session.exec(select(Student).where(Student.roll_number == log.student_roll, Student.institute_name == user.institute_name)).first()
        name = student.name if student else "Unknown"
        local_time_obj = log.timestamp.astimezone(ist)
        data.append({"Roll Number": log.student_roll, "Name": name, "Time": local_time_obj.strftime("%H:%M:%S"), "Status": log.status})
    
    df = pd.DataFrame(data, columns=["Roll Number", "Name", "Time", "Status"])
    filename = f"Attendance_{class_session.course_name}_{class_session.batch_name}.xlsx"
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
    output.seek(0)
    return StreamingResponse(output, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={"Content-Disposition": f"attachment; filename={filename}"})

@router.get("/api/download_course_report/{course_id}")
async def download_course_report(course_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course or course.instructor_user != user.username: 
        raise HTTPException(403, "Access Denied")
    
    links = session.exec(select(StudentCourseLink).where(StudentCourseLink.course_id == course_id)).all()
    student_ids = [l.student_id for l in links]
    if not student_ids: raise HTTPException(400, "No students enrolled in this course")
    
    students = session.exec(select(Student).where(Student.id.in_(student_ids))).all()
    student_map = {s.roll_number: s for s in students}
    all_rolls = list(student_map.keys())
    
    sessions = session.exec(select(ClassSession).where(ClassSession.course_id == course_id).order_by(ClassSession.date_str)).all()
    
    session_map = {s.id: s.date_str[:10] for s in sessions}
    session_ids = list(session_map.keys())
    logs = session.exec(select(AttendanceLog).where(AttendanceLog.session_id.in_(session_ids))).all()
    attendance_lookup = set((log.student_roll, log.session_id) for log in logs)
    
    data = []
    for roll in all_rolls:
        stu_obj = student_map[roll]
        row = {
            "Roll Number": roll, 
            "Name": stu_obj.name,
            "Branch": stu_obj.branch if stu_obj.branch else "N/A"
        }
        for sess in sessions:
            date_col = f"{sess.date_str[:10]} ({sess.batch_name})"
            row[date_col] = "P" if (roll, sess.id) in attendance_lookup else "A"
        data.append(row)
    
    df = pd.DataFrame(data)
    cols = ["Roll Number", "Name", "Branch"] + [c for c in df.columns if c not in ["Roll Number", "Name", "Branch"]]
    df = df[cols]
    
    filename = f"Master_Attendance_{course.name}.xlsx"
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False, sheet_name="Attendance")
    output.seek(0)
    return StreamingResponse(output, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={"Content-Disposition": f"attachment; filename={filename}"})
