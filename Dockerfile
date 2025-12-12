# Use Miniconda (Lightweight, Pre-built binaries)
FROM continuumio/miniconda3

# 1. Set Working Directory
WORKDIR /app

# 2. Install System compilers
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. Install Heavy AI Libraries via Conda (PRE-BUILT BINARIES)
# We install these FIRST so they are definitely present before pip runs
RUN conda install -y -c conda-forge dlib face_recognition numpy pandas

# 4. Install Web & App Libraries via Pip (Hardcoded List)
# We list them here directly to ensure NO "ghost" dependencies from cached files
RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    python-multipart==0.0.9 \
    sqlmodel==0.0.19 \
    opencv-python-headless==4.10.0.82 \
    python-jose==3.3.0 \
    passlib[bcrypt]==1.7.4 \
    bcrypt==4.0.1 \
    openpyxl==3.1.5 \
    requests==2.32.3

# 5. Copy Application Code
COPY . .

# 6. Expose Port
EXPOSE 8000

# 7. Start Command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
