from pydantic import BaseModel
from typing import Optional

# --- AUTHENTICATION ---
class InstructorRegister(BaseModel):
    username: str
    password: str
    institute_name: str
    master_key: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

# --- ACADEMIC / COURSE MANAGEMENT ---
class CourseCreate(BaseModel):
    name: str

# Modified: Removed course_id, Branch is now mandatory
class StudentRegisterRequest(BaseModel):
    rollNumber: str
    name: str
    photoBase64: str
    branch: str 

# NEW: For adding a single existing student to a course
class EnrollStudentRequest(BaseModel):
    course_id: int
    roll_number: str

# NEW: For adding a whole branch to a course
class EnrollBranchRequest(BaseModel):
    course_id: int
    branch: str

# NEW: For removing a student from a course
class DropStudentRequest(BaseModel):
    course_id: int
    roll_number: str

# --- ATTENDANCE ---
class AttendanceRequest(BaseModel):
    instituteName: str
    rollNumber: str
    qrCodeData: str
    photoBase64: str
    timestamp: str

class CreateSessionRequest(BaseModel):
    course_id: int 
    course_name: str
    batch_name: str
    date_str: str
