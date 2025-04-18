# Use Python 3.11 slim image
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies and Google Cloud SDK
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    gnupg \
    lsb-release \
    && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] http://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key --keyring /usr/share/keyrings/cloud.google.gpg add - \
    && apt-get update && apt-get install -y google-cloud-sdk \
    && rm -rf /var/lib/apt/lists/*

# Create entrypoint script
RUN echo '#!/bin/sh\n\
if [ -n "$GOOGLE_CLOUD_PROJECT" ]; then\n\
    gcloud config set project $GOOGLE_CLOUD_PROJECT\n\
fi\n\
exec "$@"' > /entrypoint.sh && chmod +x /entrypoint.sh

# Copy requirements first to leverage Docker cache
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/service-account.json

# Expose the port
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "backend.services.api_service"] 