import json
import io
import requests
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select, func

from database import get_session, Instructor, Course, Student, StudentCourseLink, ClassSession, AttendanceLog, ActiveQR
from auth import get_current_user
from schemas import CourseCreate, StudentRegisterRequest, EnrollBranchRequest, EnrollStudentRequest, DropStudentRequest
from utils import decode_base64, decode_image_bytes, crop_face, get_encoding_from_image, process_image_link

router = APIRouter()

# --- DASHBOARD & BASIC COURSE ROUTES ---

@router.get("/api/dashboard_stats")
async def get_stats(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    total_students = session.exec(select(func.count(Student.id)).where(Student.institute_name == user.institute_name)).one()
    courses = session.exec(select(Course).where(Course.instructor_user == user.username)).all()
    course_names = [c.name for c in courses]
    return {
        "institute": user.institute_name,
        "total_students": total_students,
        "active_courses": len(courses),
        "course_list": course_names
    }

@router.post("/api/courses")
async def create_course(body: CourseCreate, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    new_course = Course(name=body.name, institute_name=user.institute_name, instructor_user=user.username)
    session.add(new_course)
    session.commit()
    return {"success": True, "id": new_course.id, "name": new_course.name}

@router.get("/api/courses")
async def get_courses(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    return session.exec(select(Course).where(Course.instructor_user == user.username)).all()

@router.delete("/api/courses/{course_id}")
async def delete_course(course_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course or course.instructor_user != user.username: 
        raise HTTPException(403, "Not Authorized")
    
    links = session.exec(select(StudentCourseLink).where(StudentCourseLink.course_id == course_id)).all()
    for link in links: session.delete(link)

    sessions = session.exec(select(ClassSession).where(ClassSession.course_id == course_id)).all()
    for sess in sessions:
        logs = session.exec(select(AttendanceLog).where(AttendanceLog.session_id == sess.id)).all()
        for log in logs: session.delete(log)
        qrs = session.exec(select(ActiveQR).where(ActiveQR.session_id == sess.id)).all()
        for qr in qrs: session.delete(qr)
        session.delete(sess)

    session.delete(course)
    session.commit()
    return {"success": True}

# --- GLOBAL STUDENT DATABASE ROUTES ---

@router.get("/api/students")
async def get_all_students(user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    """Get ALL students in the institute (Global List)"""
    students = session.exec(select(Student).where(Student.institute_name == user.institute_name)).all()
    return [{"id": s.id, "roll_number": s.roll_number, "name": s.name, "branch": s.branch} for s in students]

@router.post("/api/register")
async def register_student(body: StudentRegisterRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    """Registers a student to the INSTITUTE database. Does NOT enroll in a course."""
    clean_branch = body.branch.strip().upper()
    if not clean_branch:
        raise HTTPException(400, "Branch is mandatory")

    student = session.exec(select(Student).where(Student.roll_number == body.rollNumber, Student.institute_name == user.institute_name)).first()
    
    if student:
        # Update existing student details
        student.name = body.name
        student.branch = clean_branch
        # Only update photo if provided? For now, we assume registration implies setting photo.
        # But if they just want to update metadata, we could skip photo.
        # Following strict prompt: "student will be added with pic name roll no and branch"
    else:
        # New Student
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
            branch=clean_branch, 
            face_encoding_json=json.dumps(encoding)
        )
        session.add(student)
    
    session.commit()
    return {"success": True, "message": "Student Saved to Database"}

@router.post("/api/bulk_register")
async def bulk_register(file: UploadFile = File(...), user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    """Bulk imports students to the INSTITUTE database. CSV Cols: roll_no, name, branch, image_link"""
    contents = await file.read()
    try:
        if file.filename.lower().endswith('.csv'): 
            df = pd.read_csv(io.BytesIO(contents))
        else: 
            df = pd.read_excel(io.BytesIO(contents))
        df.columns = [c.strip().lower() for c in df.columns]
    except: raise HTTPException(400, "Invalid file format")

    success_count = 0
    errors = []
    
    for _, row in df.iterrows():
        try:
            roll = str(row.get('roll_no', '')).strip()
            name = str(row.get('name', '')).strip()
            branch = str(row.get('branch', '')).strip().upper()
            link_url = str(row.get('image_link', '')).strip()

            if not roll or not name or not branch or not link_url:
                continue
            
            link_url = process_image_link(link_url)

            student = session.exec(select(Student).where(Student.roll_number == roll, Student.institute_name == user.institute_name)).first()
            
            if not student:
                # Download and process image
                headers = {'User-Agent': 'Mozilla/5.0'}
                response = requests.get(link_url, headers=headers, timeout=10)
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
                            branch=branch,
                            face_encoding_json=json.dumps(encoding)
                        )
                        session.add(student)
                        success_count += 1
                    else:
                        errors.append(f"{roll}: No face found")
                else:
                    errors.append(f"{roll}: Link error")
            else:
                # Update existing branch
                student.branch = branch
                session.add(student)
                success_count += 1

        except Exception as e:
            errors.append(f"{roll}: Processing Error")
            continue
            
    session.commit()
    return {"success": True, "added": success_count, "errors": errors}

@router.delete("/api/students/{student_id}")
async def delete_student(student_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    student = session.get(Student, student_id)
    if not student or student.institute_name != user.institute_name: raise HTTPException(403, "Not Authorized")
    
    links = session.exec(select(StudentCourseLink).where(StudentCourseLink.student_id == student_id)).all()
    for link in links: session.delete(link)
    
    # Optional: Delete logs
    logs = session.exec(select(AttendanceLog).where(AttendanceLog.student_roll == student.roll_number)).all()
    for log in logs: session.delete(log)

    session.delete(student)
    session.commit()
    return {"success": True}


# --- COURSE MANAGEMENT CENTER (NEW) ---

@router.get("/api/course_students/{course_id}")
async def get_course_students(course_id: int, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    """Get students enrolled in a specific course"""
    course = session.get(Course, course_id)
    if not course or course.instructor_user != user.username: raise HTTPException(403, "Access Denied")

    links = session.exec(select(StudentCourseLink).where(StudentCourseLink.course_id == course_id)).all()
    student_ids = [l.student_id for l in links]
    
    if not student_ids: return []
    
    students = session.exec(select(Student).where(Student.id.in_(student_ids))).all()
    return [{"roll_number": s.roll_number, "name": s.name, "branch": s.branch} for s in students]

@router.post("/api/enroll_student")
async def enroll_student(body: EnrollStudentRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    """Add a single existing student to a course by Roll No"""
    course = session.get(Course, body.course_id)
    if not course or course.instructor_user != user.username: raise HTTPException(403, "Access Denied")

    student = session.exec(select(Student).where(Student.roll_number == body.roll_number, Student.institute_name == user.institute_name)).first()
    if not student: raise HTTPException(404, "Student not found in database")

    existing_link = session.exec(select(StudentCourseLink).where(StudentCourseLink.student_id == student.id, StudentCourseLink.course_id == body.course_id)).first()
    if not existing_link:
        session.add(StudentCourseLink(student_id=student.id, course_id=body.course_id))
        session.commit()
        return {"success": True, "message": "Student Enrolled"}
    return {"success": True, "message": "Already Enrolled"}

@router.post("/api/enroll_branch")
async def enroll_branch(body: EnrollBranchRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    """Add ALL students of a specific branch to a course"""
    course = session.get(Course, body.course_id)
    if not course or course.instructor_user != user.username: raise HTTPException(403, "Access Denied")
    
    target_branch = body.branch.strip().upper()
    students = session.exec(select(Student).where(Student.branch == target_branch, Student.institute_name == user.institute_name)).all()
    
    if not students: return {"success": False, "message": f"No students found in branch '{target_branch}'"}

    count = 0
    for s in students:
        link = session.exec(select(StudentCourseLink).where(StudentCourseLink.student_id == s.id, StudentCourseLink.course_id == body.course_id)).first()
        if not link:
            session.add(StudentCourseLink(student_id=s.id, course_id=body.course_id))
            count += 1
    session.commit()
    return {"success": True, "message": f"Enrolled {count} students from {target_branch}"}

@router.post("/api/drop_student")
async def drop_student(body: DropStudentRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    """Remove a student from a course"""
    course = session.get(Course, body.course_id)
    if not course or course.instructor_user != user.username: raise HTTPException(403, "Access Denied")

    student = session.exec(select(Student).where(Student.roll_number == body.roll_number, Student.institute_name == user.institute_name)).first()
    if not student: raise HTTPException(404, "Student not found")

    link = session.exec(select(StudentCourseLink).where(StudentCourseLink.student_id == student.id, StudentCourseLink.course_id == body.course_id)).first()
    if link:
        session.delete(link)
        session.commit()
        return {"success": True, "message": "Student Dropped"}
    
    return {"success": False, "message": "Student was not enrolled"}
