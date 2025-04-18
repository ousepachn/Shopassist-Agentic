# ShopAssist V2 - Agent-based Scraper

A powerful Instagram scraping and analysis tool that uses AI to process content and enables semantic search through a vector database.

## Features

- **Instagram Scraping**: Scrape posts, reels, and stories from Instagram profiles
- **AI Content Analysis**: Process media content using Google's Vertex AI
- **Vector Database Integration**: Store and index content in Pinecone for semantic search
- **Semantic Search**: Find relevant content using natural language queries
- **API Service**: RESTful API for all functionality
- **Scheduled Sync**: Automated synchronization with vector database

## Prerequisites

- Python 3.8+
- Google Cloud Platform account with Vertex AI enabled
- Pinecone account
- Firebase account
- Instagram API access (via RapidAPI)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/ShopAssist-V2.git
   cd ShopAssist-V2/SA-AgentbasedScraper
   ```

2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

3. Set up environment variables:
   Create a `.env.local` file in the project root with the following variables:
   ```
   # Firebase
   FIREBASE_SERVICE_ACCOUNT_PATH=path/to/your/firebase-credentials.json
   FIREBASE_PROJECT_ID=your-firebase-project-id
   
   # Google Cloud
   GOOGLE_APPLICATION_CREDENTIALS=path/to/your/google-credentials.json
   GOOGLE_CLOUD_LOCATION=us-central1
   
   # Pinecone
   PINECONE_API_KEY=your-pinecone-api-key
   PINECONE_INDEX_NAME=shopassist-v2
   
   # RapidAPI
   RAPIDAPI_KEY=your-rapidapi-key
   ```

4. Authenticate with Google Cloud:
   ```bash
   gcloud auth application-default login
   ```

## Usage

### 1. Scraping Instagram Content

#### Using the API

```bash
curl -X POST "http://localhost:8000/api/scrape" \
  -H "Content-Type: application/json" \
  -d '{"username": "recipesbypooh", "max_posts": 50, "process_with_vertex_ai": true}'
```

#### Using the Python Module

```python
from backend.scrapers.instagram_scraper import InstagramScraper

# Initialize scraper
scraper = InstagramScraper(api_key="your-rapidapi-key")

# Scrape profile
metadata_df = scraper.process_profile("recipesbypooh", max_posts=50)
```

### 2. Processing Content with AI

#### Using the API

```bash
curl -X POST "http://localhost:8000/api/process-ai" \
  -H "Content-Type: application/json" \
  -d '{"username": "recipesbypooh", "processing_option": "update_remaining"}'
```

#### Using the Python Module

```python
from backend.scrapers.instagram_scraper import InstagramScraper

# Initialize scraper
scraper = InstagramScraper(api_key="your-rapidapi-key")

# Process content with AI
metadata_df = scraper.run_ai_processing("recipesbypooh", processing_option="update_remaining")
```

### 3. Syncing with Vector Database

#### Using the Scheduler

```bash
# Run once
python backend/run_sync_scheduler.py --run-once

# Run with scheduling (every 4 hours)
python backend/run_sync_scheduler.py --interval 4

# Run for a specific username
python backend/run_sync_scheduler.py --username recipesbypooh
```

#### Using the Python Module

```python
from backend.services.pinecone_sync import PineconeSync

# Initialize sync service
sync = PineconeSync(username="recipesbypooh")

# Sync to Pinecone
sync.sync_to_pinecone()
```

### 4. Searching the Vector Database

#### Using the API

```bash
curl -X POST "http://localhost:8000/api/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "recipe for chocolate cake", "top_k": 5}'
```

#### Using the Python Module

```python
from backend.services.search_service import SearchService

# Initialize search service
search_service = SearchService()

# Search for posts
results = search_service.search_posts("recipe for chocolate cake", top_k=5)

# Display results
for result in results:
    print(f"Score: {result['score']}")
    print(f"Content: {result['content']}")
    print(f"Caption: {result['caption']}")
    print("---")
```

#### Using the CLI

```bash
# Basic search
python -m backend.services.search_service "recipe for chocolate cake"

# Search with options
python -m backend.services.search_service "recipe for chocolate cake" --top-k 10 --verbose
```

## API Endpoints

### Scraping

- `POST /api/scrape`: Scrape Instagram profile
  - Request body: `{"username": "string", "max_posts": int, "process_with_vertex_ai": bool}`
  - Response: `{"status": "string", "message": "string"}`

### AI Processing

- `POST /api/process-ai`: Process content with AI
  - Request body: `{"username": "string", "processing_option": "string"}`
  - Response: `{"status": "string", "message": "string"}`

### Status

- `GET /api/status/{username}`: Get processing status
  - Response: `{"status": "string", "message": "string", "current_post": int, "total_posts": int}`

### Search

- `POST /api/search`: Search for posts
  - Request body: `{"query": "string", "top_k": int}`
  - Response: `{"results": [{"score": float, "username": "string", "content": "string", "caption": "string", "timestamp": "string"}]}`

## Architecture

The system consists of several components:

1. **Instagram Scraper**: Fetches content from Instagram profiles
2. **AI Processor**: Analyzes media content using Google's Vertex AI
3. **Vector Database**: Stores and indexes content in Pinecone
4. **Search Service**: Enables semantic search through the vector database
5. **API Service**: Provides RESTful API for all functionality
6. **Sync Scheduler**: Automatically synchronizes content with the vector database

## Development

### Running the API Server

```bash
cd backend
uvicorn services.api_service:app --reload
```

### Running Tests

```bash
python -m pytest
```

## License

[MIT License](LICENSE)

## Deployment to Google Cloud Run

### Prerequisites for Production Deployment

- Google Cloud Platform account with billing enabled
- Google Cloud CLI installed and configured
- Docker installed locally
- Access to Google Cloud Secret Manager
- Access to Google Cloud Container Registry

### Production Environment Setup

1. **Set up Google Cloud Project**:
   ```bash
   # Create a new project (if needed)
   gcloud projects create [PROJECT_ID] --name="ShopAssist V2"
   
   # Set the current project
   gcloud config set project [PROJECT_ID]
   
   # Enable required APIs
   gcloud services enable cloudbuild.googleapis.com
   gcloud services enable run.googleapis.com
   gcloud services enable secretmanager.googleapis.com
   gcloud services enable aiplatform.googleapis.com
   gcloud services enable firestore.googleapis.com
   ```

2. **Configure Secrets in Google Cloud Secret Manager**:
   ```bash
   # Create secrets for sensitive credentials
   gcloud secrets create firebase-credentials --data-file=path/to/firebase-credentials.json
   gcloud secrets create rapidapi-key --data-file=path/to/rapidapi-key.txt
   gcloud secrets create pinecone-key --data-file=path/to/pinecone-key.txt
   gcloud secrets create instagram-token --data-file=path/to/instagram-token.txt
   ```

3. **Update CORS Configuration for Production**:
   Edit `backend/services/api_service.py` to restrict CORS to your frontend domain:
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["https://your-frontend-domain.com"],  # Replace with your frontend domain
       allow_credentials=True,
       allow_methods=["GET", "POST", "PUT", "DELETE"],
       allow_headers=["*"],
   )
   ```

4. **Configure Cloud Run Service**:
   Create a `cloudbuild.yaml` file in your project root:
   ```yaml
   steps:
     # Build the container image
     - name: 'gcr.io/cloud-builders/docker'
       args: ['build', '-t', 'gcr.io/$PROJECT_ID/shopassist-api', '.']

     # Push the container image to Container Registry
     - name: 'gcr.io/cloud-builders/docker'
       args: ['push', 'gcr.io/$PROJECT_ID/shopassist-api']

     # Deploy container image to Cloud Run
     - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
       entrypoint: gcloud
       args:
         - 'run'
         - 'deploy'
         - 'shopassist-api'
         - '--image'
         - 'gcr.io/$PROJECT_ID/shopassist-api'
         - '--region'
         - 'us-central1'
         - '--platform'
         - 'managed'
         - '--allow-unauthenticated'
         - '--port'
         - '8080'
         - '--set-env-vars'
         - 'FIREBASE_PROJECT_ID=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=us-central1,PINECONE_INDEX_NAME=shopassist-v2,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_GENAI_USE_VERTEXAI=True'
         - '--set-secrets'
         - 'FIREBASE_CREDENTIALS_JSON=firebase-credentials:latest,RAPIDAPI_KEY=rapidapi-key:latest,PINECONE_API_KEY=pinecone-key:latest,INSTAGRAM_USER_ACCESS_TOKEN=instagram-token:latest'

   images:
     - 'gcr.io/$PROJECT_ID/shopassist-api'
   ```

5. **Update Dockerfile for Production**:
   Ensure your Dockerfile is optimized for production:
   ```dockerfile
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

   # Set environment variables
   ENV PORT=8080
   ENV HOST=0.0.0.0
   ENV PYTHONUNBUFFERED=1
   ENV PYTHONPATH=/app
   ENV GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}
   ENV GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION}
   ENV GOOGLE_GENAI_USE_VERTEXAI=True

   # Expose the port
   EXPOSE 8080

   # Run the application
   CMD ["uvicorn", "backend.services.api_service:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
   ```

### Deployment Process

1. **Build and Deploy with Cloud Build**:
   ```bash
   gcloud builds submit --config cloudbuild.yaml
   ```

2. **Verify Deployment**:
   ```bash
   gcloud run services describe shopassist-api --region us-central1
   ```

3. **Test the Deployed API**:
   ```bash
   curl -X POST "https://shopassist-api-xxxxx-uc.a.run.app/api/scrape" \
     -H "Content-Type: application/json" \
     -d '{"username": "recipesbypooh", "max_posts": 50, "process_with_vertex_ai": true}'
   ```

### Production Considerations

1. **Scaling Configuration**:
   - Cloud Run automatically scales based on traffic
   - Configure min and max instances for cost optimization:
     ```bash
     gcloud run services update shopassist-api \
       --min-instances=1 \
       --max-instances=10 \
       --region=us-central1
     ```

2. **Monitoring and Logging**:
   - Set up Cloud Monitoring for your service:
     ```bash
     gcloud services enable monitoring.googleapis.com
     ```
   - View logs in Cloud Logging:
     ```bash
     gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=shopassist-api" --limit=50
     ```

3. **Security Best Practices**:
   - Use IAM roles with least privilege
   - Regularly rotate secrets
   - Consider using Cloud Armor for DDoS protection
   - Enable VPC Service Controls if needed

4. **Cost Optimization**:
   - Set up budget alerts
   - Use Cloud Run's concurrency settings to optimize resource usage
   - Consider using Cloud Run's CPU throttling for non-critical workloads

5. **Continuous Deployment**:
   - Set up Cloud Build triggers for automatic deployment on code changes
   - Implement CI/CD pipelines for testing before deployment 