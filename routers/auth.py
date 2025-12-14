from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from database import get_session, Instructor
# Imports logic from the root auth.py file
from auth import get_current_user, create_access_token, verify_password, get_password_hash, MASTER_PASSWORD
# Imports models from schemas.py
from schemas import InstructorRegister, ChangePasswordRequest

router = APIRouter()

@router.post("/api/instructor/register")
async def register_instructor(body: InstructorRegister, session: Session = Depends(get_session)):
    if body.master_key != MASTER_PASSWORD:
        raise HTTPException(403, "Access Denied: Invalid Master Key")
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

@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    user = session.get(Instructor, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "institute": user.institute_name}

@router.get("/api/me")
async def get_current_user_profile(user: Instructor = Depends(get_current_user)):
    return {
        "username": user.username,
        "institute_name": user.institute_name
    }

@router.post("/api/change_password")
async def change_password(body: ChangePasswordRequest, user: Instructor = Depends(get_current_user), session: Session = Depends(get_session)):
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid old password")
    
    user.hashed_password = get_password_hash(body.new_password)
    session.add(user)
    session.commit()
    return {"success": True, "message": "Password updated successfully"}
