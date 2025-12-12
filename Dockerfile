# STAGE 1: The Builder (Compiles the heavy stuff)
FROM python:3.10-slim as builder

# 1. Install compilers
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Force single-core compilation (Prevents RAM crash)
ENV CMAKE_BUILD_PARALLEL_LEVEL=1

# 3. Install dlib & face_recognition to a local user folder
RUN pip install --user --no-cache-dir dlib face_recognition


# STAGE 2: The Final Image (Small & Fast)
FROM python:3.10-slim

WORKDIR /app

# 1. Install runtime libraries for OpenCV & Dlib
# FIX IS HERE: Added 'libopenblas-dev' and 'liblapack-dev' to runtime
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libopenblas-dev \
    liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Copy the compiled AI libraries from the Builder Stage
COPY --from=builder /root/.local /root/.local

# 3. Add the local bin to PATH
ENV PATH=/root/.local/bin:$PATH

# 4. Install the rest of the lightweight libraries
RUN pip install --no-cache-dir --user \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    python-multipart==0.0.9 \
    sqlmodel==0.0.19 \
    numpy==1.26.4 \
    opencv-python-headless==4.10.0.82 \
    python-jose==3.3.0 \
    passlib[bcrypt]==1.7.4 \
    bcrypt==4.0.1 \
    pandas==2.2.2 \
    openpyxl==3.1.5 \
    requests==2.32.3

# 5. Copy your code
COPY . .

# 6. Run it
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
