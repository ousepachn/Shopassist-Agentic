# Use Python 3.10 slim image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend directory
COPY backend/ /app/backend/

# Create credentials directory
RUN mkdir -p /app/credentials

# Set environment variables
ENV PORT=8080
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/service-account.json
ENV GOOGLE_CLOUD_PROJECT=shopassist-agentic
ENV GOOGLE_CLOUD_LOCATION=us-central1
ENV GOOGLE_GENAI_USE_VERTEXAI=True
ENV INSTAGRAM_USER_ACCESS_TOKEN=${INSTAGRAM_USER_ACCESS_TOKEN}

# Expose the port
EXPOSE 8080

# Run the application using JSON format for better signal handling
CMD ["uvicorn", "backend.services.api_service:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"] 