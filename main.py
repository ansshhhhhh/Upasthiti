from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import create_db_and_tables

# Import Routers
from routers import auth, academic, attendance

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="Upasthiti API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(academic.router)
app.include_router(attendance.router)

@app.get("/admin")
async def admin_ui():
    return FileResponse("static/admin.html")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/icon.png")

app.mount("/static", StaticFiles(directory="static"), name="static_assets")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
