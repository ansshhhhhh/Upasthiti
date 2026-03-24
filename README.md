# Upasthiti

**Upasthiti** is a proxy-less attendance system built with **FastAPI**, **SQLModel**, **OpenCV**, and **face_recognition**. It supports instructor authentication, student registration, course management, QR-based class sessions, and face-verified attendance marking.

## Features

- Instructor registration, login, profile access, and password change
- Course creation and course-wise student enrollment
- Global institute student database
- Single and bulk student registration
- Face capture and encoding during registration
- QR-based attendance sessions
- Liveness check and face verification during attendance
- Admin UI and static frontend assets
- SQLite support by default, with optional PostgreSQL via `DATABASE_URL`
- Docker support

## Tech Stack

- **Backend:** FastAPI
- **Database:** SQLModel / SQLite / PostgreSQL
- **Computer Vision:** OpenCV, face_recognition, NumPy
- **Auth:** OAuth2 password flow, JWT, passlib, bcrypt
- **Data handling:** pandas, openpyxl, requests
- **Deployment:** Uvicorn, Docker

## Project Structure

```text
.
├── main.py                  # FastAPI app entrypoint
├── auth.py                  # Authentication helpers
├── database.py              # Database engine, models, and session setup
├── schemas.py               # Pydantic request/response schemas
├── utils.py                 # Image, face, and helper utilities
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container build instructions
├── README.md                # Project documentation
├── routers/
│   ├── __init__.py
│   ├── academic.py          # Students, courses, enrollment, dashboard APIs
│   ├── attendance.py        # Class sessions, QR generation, attendance marking
│   └── auth.py              # Instructor registration, login, profile APIs
├── static/
│   ├── index.html           # Main frontend
│   ├── admin.html           # Admin dashboard
│   ├── logo.png
│   └── icon.png
├── data/
│   └── upasthiti.db         # Local SQLite DB created at runtime
├── apk/
│   └── upasthiti.apk        # Android package file
└── .github/
    └── workflows/
        └── docker-image.yml
```

> Note: folders like `__pycache__/` and `.vscode/` are present in the repository, but they are development/runtime artifacts rather than core source files.

## Core Database Entities

The app uses these main tables:

- **Instructor** — instructor accounts and institute mapping
- **Course** — course name, institute, and owning instructor
- **Student** — student identity, branch, and face encoding
- **StudentCourseLink** — many-to-many mapping between students and courses
- **ClassSession** — active/inactive attendance sessions
- **ActiveQR** — temporary QR tokens for live sessions
- **AttendanceLog** — attendance records per session

## API Highlights

### Authentication
- `POST /api/instructor/register`
- `POST /token`
- `GET /api/me`
- `POST /api/change_password`

### Academic / Student Management
- `GET /api/dashboard_stats`
- `POST /api/courses`
- `GET /api/courses`
- `DELETE /api/courses/{course_id}`
- `GET /api/students`
- `POST /api/register`
- `POST /api/bulk_register`
- `GET /api/course_students/{course_id}`
- `POST /api/enroll_student`
- `POST /api/enroll_branch`
- `POST /api/drop_student`

### Attendance
- `POST /api/start_class`
- `POST /api/end_class`
- `GET /api/get_qr`
- `POST /api/attendance`

## How It Works

1. An instructor creates an account using the instructor registration endpoint.
2. Students are added to the institute database, either one by one or in bulk.
3. Courses are created and students are enrolled into specific courses.
4. When a class starts, the backend creates an active session and generates a temporary QR token.
5. A student scans the QR and submits a selfie image.
6. The backend checks:
   - QR validity
   - QR expiry
   - liveness
   - face match
   - active class session
   - institute match
7. If everything passes, attendance is stored in the database.

## Local Setup

### 1) Clone the repository

```bash
git clone https://github.com/ansshhhhhh/Upasthiti.git
cd Upasthiti
```

### 2) Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Configure the database

By default, the app creates a local SQLite database at:

```text
data/upasthiti.db
```

If you want to use PostgreSQL or another supported database, set:

```bash
export DATABASE_URL="your_database_url"
```

The app will automatically use `DATABASE_URL` if it is provided.

### 5) Run the app

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Then open the app in your browser.

## Docker

Build and run the container:

```bash
docker build -t upasthiti .
docker run -p 8000:8000 upasthiti
```

The repository also includes a GitHub Actions workflow at `.github/workflows/docker-image.yml` for Docker-based automation.

## Development Notes

- The FastAPI app initializes the database on startup.
- Static files are served from `static/`.
- `/admin` serves `static/admin.html`.
- `/favicon.ico` serves `static/icon.png`.
- The root path `/` is mounted to the static frontend.

## License

This project is licensed under the Apache-2.0 License.

