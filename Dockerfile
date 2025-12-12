# Use Miniconda (Lightweight, Pre-built binaries)
FROM continuumio/miniconda3

# 1. Set Working Directory
WORKDIR /app

# 2. Install System compilers (Prevents "gcc not found" errors)
# We need libgl1 for OpenCV and build-essential for bcrypt/others
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. Copy Requirements
COPY requirements.txt .

# 4. Install Heavy AI Libraries via Conda (PRE-BUILT BINARIES)
# This installs dlib and face_recognition without compiling
RUN conda install -y -c conda-forge dlib face_recognition

# 5. Install the rest using pip
# We use --ignore-installed to prevent pip from clashing with conda packages
RUN pip install --no-cache-dir --ignore-installed -r requirements.txt

# 6. Copy Application Code
COPY . .

# 7. Expose Port
EXPOSE 8000

# 8. Start Command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
