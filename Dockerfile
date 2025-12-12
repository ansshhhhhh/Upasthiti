# Use Python 3.10 Slim (Smaller, faster)
FROM python:3.10-slim

# 1. Install System Dependencies required for Face Recognition & OpenCV
# dlib needs cmake and build-essential (GCC) to compile
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

# 3. Copy Requirements first (to cache dependencies)
COPY requirements.txt .

# 4. Install Python Dependencies
# (This step will take 5-10 minutes because dlib has to compile)
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the application
COPY . .

# 6. Expose the port
EXPOSE 8000

# 7. Create a volume mount point for the database (So data isn't lost on restart)
VOLUME /app/data

# 8. Start Command
# We use --host 0.0.0.0 so it is accessible outside the container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
