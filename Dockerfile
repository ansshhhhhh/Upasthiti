# STAGE 1: Builder (Compiles dlib so you don't have to)
FROM python:3.10-slim as builder

# Install build tools
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dlib & face_recognition
# This takes ~10-15 mins. BE PATIENT. It only runs once.
RUN pip install --user --no-cache-dir face_recognition


# STAGE 2: Final Runtime (Lightweight & Fast)
FROM python:3.10-slim

WORKDIR /app

# 1. Install CRITICAL runtime libraries
# These are the files that were missing before (libjpeg, libpng, openblas)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libopenblas0 \
    libjpeg62-turbo \
    libpng16-16 \
    libx11-6 \
    && rm -rf /var/lib/apt/lists/*

# 2. Copy compiled libraries from builder
COPY --from=builder /root/.local /root/.local

# 3. Add to PATH
ENV PATH=/root/.local/bin:$PATH

# 4. Install other dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy App Code
COPY . .

# 6. Run
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
