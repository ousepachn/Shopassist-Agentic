#!/bin/bash

# Exit on error
set -e

echo "Building Docker image..."
docker build -t shopassist-backend .

echo "Running Docker container..."
# Run the container with environment variables
docker run -p 8080:8080 \
  -e FIREBASE_SERVICE_ACCOUNT_PATH=/app/credentials/service-account.json \
  -e RAPIDAPI_KEY=${RAPIDAPI_KEY} \
  -e FIREBASE_API_KEY=${FIREBASE_API_KEY} \
  -e FIREBASE_AUTH_DOMAIN=${FIREBASE_AUTH_DOMAIN} \
  -e FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID} \
  -e FIREBASE_STORAGE_BUCKET=${FIREBASE_STORAGE_BUCKET} \
  -e FIREBASE_MESSAGING_SENDER_ID=${FIREBASE_MESSAGING_SENDER_ID} \
  -e FIREBASE_APP_ID=${FIREBASE_APP_ID} \
  -e FIREBASE_MEASUREMENT_ID=${FIREBASE_MEASUREMENT_ID} \
  -e GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT} \
  -e GOOGLE_CLOUD_REGION=${GOOGLE_CLOUD_REGION} \
  -e GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION} \
  -e GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/service-account.json \
  -v $(pwd)/credentials:/app/credentials \
  shopassist-backend

echo "Container started. Access the API at http://localhost:8080" 