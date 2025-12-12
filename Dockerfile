# Use Miniconda (Lightweight version of Anaconda)
# This comes with pre-built binaries for data science
FROM continuumio/miniconda3

# 1. Set Working Directory
WORKDIR /app

# 2. Install System libraries for OpenCV (GL libraries)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. Copy Requirements
COPY requirements.txt .

# --- THE MAGIC PART ---
# Instead of compiling dlib (which kills your server), we download it.
# We verify the channel is conda-forge to get the latest binaries.
RUN conda install -y -c conda-forge dlib cmake

# 4. Install the rest using pip
# We install the pinned bcrypt here to ensure stability
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy Application Code
COPY . .

# 6. Expose Port
EXPOSE 8000

# 7. Start Command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
