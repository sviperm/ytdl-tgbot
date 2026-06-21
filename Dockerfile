# Use an official Python runtime as a parent image
FROM python:3.14-slim

# Set environmental variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Deno: JavaScript runtime yt-dlp needs to solve YouTube signature / n-param
# challenges (via yt-dlp-ejs). Without it YouTube downloads fail with HTTP 403.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# Set the working directory in the container
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create necessary directories
RUN mkdir -p log downloads

# Start the bot
CMD ["python", "main.py"]
