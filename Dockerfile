# Use Miniconda
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

# 3. Copy Requirements
COPY requirements.txt .

# 4. Install Heavy AI Libraries via Conda
# We install dlib and face_recognition here so we get pre-built binaries
RUN conda install -y -c conda-forge dlib face_recognition

# 5. Install the rest using pip
# CRITICAL FIX: Removed "--ignore-installed" so pip sees the Conda packages
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy Application Code
COPY . .

# 7. Expose Port
EXPOSE 8000

# 8. Start Command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]