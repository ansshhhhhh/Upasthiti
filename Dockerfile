# Use Python 3.10 Slim
FROM python:3.10-slim

# 1. Set Working Directory
WORKDIR /app

# 2. Install System Dependencies for OpenCV
# We only need basic GL libraries now, no heavy compilers
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. Copy Requirements
COPY requirements.txt .

# 4. Install Dependencies
# This will install deepface and tensorflow automatically
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy Application Code
COPY . .

# 6. Expose Port
EXPOSE 8000

# 7. Start Command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
