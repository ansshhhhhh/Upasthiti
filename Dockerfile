# 1. Use an official lightweight Python image
FROM python:3.10-slim

# 2. Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

# 3. Install System Dependencies
# FIX: Replaced 'libgl1-mesa-glx' with 'libgl1' (New Debian name)
# KEEP: 'libpq-dev' for Postgres and 'cmake' for Face Recognition
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libpq-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 4. Set working directory
WORKDIR /app

# 5. Copy requirements first (to leverage Docker caching)
COPY requirements.txt .

# 6. Install Python Dependencies
# KEEP: --default-timeout=1000 to solve your "ReadTimeoutError"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

# 7. Copy the rest of the application code
COPY . .

# 8. Expose the port
EXPOSE 8000

# 9. Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
