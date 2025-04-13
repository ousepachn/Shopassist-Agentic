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