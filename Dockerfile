# Use Python 3.10 Slim
FROM python:3.10-slim

# 1. Install System Dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# 2. Set Working Directory
WORKDIR /app

# 3. Copy Requirements
COPY requirements.txt .

# --- CRITICAL FIX START ---
# Force dlib to compile using only 1 CPU core.
# This prevents the "Out of Memory" (OOM) error.
ENV CMAKE_BUILD_PARALLEL_LEVEL=1
# --- CRITICAL FIX END ---

# 4. Install Dependencies (This will now take 10-15 minutes, be patient!)
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy Application
COPY . .

# 6. Expose Port
EXPOSE 8000

# 7. Create Volume for Data
# Note: Render Free Tier does not support persistent volumes, 
# so 'data' will reset on every deploy. This is fine for testing.
VOLUME /app/data

# 8. Start Command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
