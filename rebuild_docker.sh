#!/bin/bash

# Stop the running containers
echo "Stopping running containers..."
docker-compose down

# Rebuild the containers with the new configuration
echo "Rebuilding containers..."
docker-compose build

# Start the containers
echo "Starting containers..."
docker-compose up -d

# Show logs
echo "Showing logs..."
docker-compose logs -f 