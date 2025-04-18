from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
from dotenv import load_dotenv
from backend.scrapers.instagram_scraper import InstagramScraper
import firebase_admin
from firebase_admin import credentials, firestore
import json
import subprocess
import logging
import numpy as np
import traceback
from pathlib import Path
import pandas as pd
from backend.services.search_service import SearchService
import httpx
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel, Part
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("api_service.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Test log message
logger.info("API Service starting up...")

# Load environment variables
load_dotenv()

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Initialize Firebase Admin with resolved path
firebase_creds_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

# Check for credentials in Docker container's /credentials folder
docker_creds_path = "/app/credentials/firebase-credentials.json"
if os.path.exists(docker_creds_path):
    logger.info(
        f"Using Firebase credentials from Docker container: {docker_creds_path}"
    )
    firebase_creds_path = docker_creds_path

if firebase_creds_json:
    # Use credentials from environment variable
    try:
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("Firebase initialized with credentials from environment variable")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse FIREBASE_CREDENTIALS_JSON: {str(e)}")
        raise ValueError("Invalid FIREBASE_CREDENTIALS_JSON format")
elif firebase_creds_path:
    # Fall back to file-based credentials
    if not os.path.isabs(firebase_creds_path):
        firebase_creds_path = str(PROJECT_ROOT / firebase_creds_path)
    if not os.path.exists(firebase_creds_path):
        logger.error(f"Firebase credentials file not found at: {firebase_creds_path}")
        raise ValueError(
            f"Firebase credentials file not found at: {firebase_creds_path}"
        )
    try:
        cred = credentials.Certificate(firebase_creds_path)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info(
            f"Firebase initialized with credentials from file: {firebase_creds_path}"
        )
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Firebase credentials file: {str(e)}")
        raise ValueError(
            f"Invalid Firebase credentials file format: {firebase_creds_path}"
        )
else:
    logger.error("No Firebase credentials found in environment variables")
    raise ValueError(
        "No Firebase credentials found. Please set either FIREBASE_CREDENTIALS_JSON or FIREBASE_SERVICE_ACCOUNT_PATH"
    )

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins during development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    username: str
    max_posts: Optional[int] = 50
    process_with_vertex_ai: Optional[bool] = False


class ProcessAIRequest(BaseModel):
    username: str
    processing_option: str = (
        "update_remaining"  # 'update_all', 'update_remaining', or 'skip'
    )


class VerifyRequest(BaseModel):
    username: str


class ScrapeStatus(BaseModel):
    status: str
    total_posts: Optional[int] = None
    current_post: Optional[int] = None
    profile_name: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class ProcessingStatus(BaseModel):
    scraping: ScrapeStatus
    ai_processing: ScrapeStatus


class VerifyStatus(BaseModel):
    status: str
    message: Optional[str] = None
    error: Optional[str] = None
    missing_files: Optional[List[str]] = None
    unreferenced_files: Optional[List[str]] = None


class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    instagram_recipient_id: str


def check_gcloud_auth():
    """Check if Google Cloud authentication is available"""
    try:
        # Check if we're in a Docker container
        is_docker = os.path.exists("/.dockerenv")

        # Check for service account credentials
        creds_paths = [
            # Docker container paths
            "/app/credentials/service-account.json",
            "/app/credentials/instagram-scraper-service-account.json",
            # Local paths
            os.path.join(PROJECT_ROOT, "credentials", "service-account.json"),
            os.path.join(
                PROJECT_ROOT, "credentials", "instagram-scraper-service-account.json"
            ),
            # Environment variable path
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        ]

        # Filter out empty paths
        creds_paths = [p for p in creds_paths if p]

        # Check each path
        for path in creds_paths:
            if os.path.exists(path):
                logger.info(f"Using Google Cloud credentials from: {path}")
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
                return True

        # If we're in Docker, we can't use gcloud CLI
        if is_docker:
            logger.error("Running in Docker but no service account credentials found.")
            logger.error("Please ensure one of the following files exists:")
            for path in creds_paths:
                logger.error(f"  - {path}")
            return False

        # For local development, try gcloud CLI
        try:
            # Check if gcloud is installed
            subprocess.run(["gcloud", "--version"], check=True, capture_output=True)

            # Check if application-default credentials exist
            credentials_path = os.path.expanduser(
                "~/.config/gcloud/application_default_credentials.json"
            )
            if not os.path.exists(credentials_path):
                logger.error("Application Default Credentials not found. Please run:")
                logger.error("gcloud auth application-default login")
                return False

            # Check if project ID is set
            result = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True,
                text=True,
            )
            if not result.stdout.strip():
                logger.error("No default project set. Please run:")
                logger.error("gcloud config set project YOUR_PROJECT_ID")
                return False

            return True
        except subprocess.CalledProcessError:
            logger.error("gcloud CLI not found. Please install the Google Cloud CLI:")
            logger.error("https://cloud.google.com/sdk/docs/install")
            return False
    except Exception as e:
        logger.error(f"Error checking Google Cloud authentication: {str(e)}")
        return False


def setup_vertex_ai():
    """Set up Vertex AI client and return project ID"""
    try:
        # Check if we're in a Docker container
        is_docker = os.path.exists("/.dockerenv")

        # Get project ID from environment variable first
        project_id = os.getenv("FIREBASE_PROJECT_ID")

        # If not set, try to get it from the service account file
        if not project_id:
            # Check for service account credentials
            creds_paths = [
                # Docker container paths
                "/app/credentials/service-account.json",
                "/app/credentials/instagram-scraper-service-account.json",
                # Local paths
                os.path.join(PROJECT_ROOT, "credentials", "service-account.json"),
                os.path.join(
                    PROJECT_ROOT,
                    "credentials",
                    "instagram-scraper-service-account.json",
                ),
                # Environment variable path
                os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
            ]

            # Filter out empty paths
            creds_paths = [p for p in creds_paths if p]

            # Check each path
            for path in creds_paths:
                if os.path.exists(path):
                    try:
                        with open(path, "r") as f:
                            creds_data = json.load(f)
                            if "project_id" in creds_data:
                                project_id = creds_data["project_id"]
                                logger.info(
                                    f"Using project ID from service account: {project_id}"
                                )
                                break
                    except (json.JSONDecodeError, IOError) as e:
                        logger.warning(
                            f"Error reading credentials file {path}: {str(e)}"
                        )

        # If we're in Docker and still don't have a project ID, we can't proceed
        if is_docker and not project_id:
            logger.error("Running in Docker but couldn't determine project ID.")
            logger.error(
                "Please ensure FIREBASE_PROJECT_ID is set or a valid service account file exists."
            )
            return None

        # For local development, try gcloud CLI if we don't have a project ID
        if not project_id and not is_docker:
            try:
                result = subprocess.run(
                    ["gcloud", "config", "get-value", "project"],
                    capture_output=True,
                    text=True,
                )
                if result.stdout.strip():
                    project_id = result.stdout.strip()
                    logger.info(f"Using project ID from gcloud: {project_id}")
            except subprocess.CalledProcessError:
                logger.warning("Failed to get project ID from gcloud CLI")

        if not project_id:
            logger.error("Could not determine Google Cloud project ID")
            return None

        # Set up Vertex AI client
        aiplatform.init(project=project_id, location="us-central1")
        logger.info(f"Vertex AI client initialized with project: {project_id}")
        return project_id
    except Exception as e:
        logger.error(f"Error setting up Vertex AI: {str(e)}")
        return None


def convert_to_firestore_compatible(data):
    """
    Convert data to be compatible with Firestore by handling NumPy arrays and other non-serializable types.
    """
    logger.debug(f"Converting data to Firestore compatible format: {type(data)}")

    if isinstance(data, np.ndarray):
        logger.debug(f"Converting NumPy array to list: {data.shape}")
        return data.tolist()
    elif isinstance(data, dict):
        logger.debug("Converting dictionary")
        return {k: convert_to_firestore_compatible(v) for k, v in data.items()}
    elif isinstance(data, list):
        logger.debug(f"Converting list of length {len(data)}")
        return [convert_to_firestore_compatible(item) for item in data]
    elif isinstance(data, (np.int64, np.int32, np.float64, np.float32)):
        logger.debug(f"Converting NumPy numeric type to Python native: {type(data)}")
        return data.item()
    elif pd.isna(data):  # Handle pandas NaT and NaN values
        logger.debug(f"Converting pandas NaT/NaN value to None")
        return None
    else:
        return data


@app.post("/api/scrape")
async def scrape_profile(request: ScrapeRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"Starting scrape for username: {request.username}")
        # Initialize scraper
        api_key = os.getenv("RAPIDAPI_KEY")
        if not api_key:
            logger.error("API key not configured")
            raise HTTPException(status_code=500, detail="API key not configured")

        # Check gcloud authentication and setup
        if not check_gcloud_auth():
            logger.error("Google Cloud authentication not configured")
            raise HTTPException(
                status_code=500,
                detail="Google Cloud authentication not configured. Please run 'gcloud auth application-default login'",
            )

        # Setup Vertex AI and get project ID
        project_id = setup_vertex_ai()
        if not project_id:
            logger.error("Failed to set up Vertex AI")
            raise HTTPException(
                status_code=500,
                detail="Failed to set up Vertex AI. Please check your Google Cloud configuration.",
            )

        logger.info(f"Using project ID: {project_id}")

        # Initialize scraper with project ID and vertex_ai preference
        scraper = InstagramScraper(
            api_key,
            project_id=project_id,
            auto_process_with_vertex=request.process_with_vertex_ai,
        )

        # Initialize status in Firestore
        doc_ref = db.collection("scraping_results").document(request.username)
        doc_ref.set(
            {
                "status": "initializing",
                "timestamp": firestore.SERVER_TIMESTAMP,
                "message": "Starting scrape process...",
                "current_post": 0,
                "total_posts": 0,
            }
        )

        # Start scraping in background
        def process_scraping():
            try:
                # Get metadata
                doc_ref.update(
                    {
                        "status": "fetching_profile",
                        "message": "Fetching profile information...",
                    }
                )

                # Process profile with automatic Vertex AI handling
                logger.info(f"Processing profile for {request.username}")
                metadata_df = scraper.process_profile(
                    request.username, request.max_posts
                )

                if metadata_df is not None:
                    total_posts = len(metadata_df)
                    logger.info(f"Found {total_posts} posts to process")
                    doc_ref.update(
                        {
                            "status": "in_progress",
                            "message": f"Found {total_posts} posts to process",
                            "total_posts": total_posts,
                        }
                    )

                    # Convert metadata to dict for Firestore
                    logger.debug("Converting metadata DataFrame to dictionary")
                    metadata_dict = metadata_df.to_dict(orient="records")

                    # Convert NumPy arrays to lists for Firestore compatibility
                    logger.debug("Converting data to Firestore compatible format")
                    firestore_compatible_metadata = convert_to_firestore_compatible(
                        metadata_dict
                    )

                    # Download media with progress updates
                    for idx, post in enumerate(firestore_compatible_metadata, 1):
                        logger.debug(f"Processing post {idx}/{total_posts}")
                        doc_ref.update(
                            {
                                "current_post": idx,
                                "message": f"Processing post {idx}/{total_posts}",
                            }
                        )

                    # Final update
                    logger.info(f"Successfully processed {total_posts} posts")
                    doc_ref.update(
                        {
                            "status": "completed",
                            "message": f"Successfully processed {total_posts} posts{' with Vertex AI' if request.process_with_vertex_ai else ''}",
                            "metadata": firestore_compatible_metadata,
                            "timestamp": firestore.SERVER_TIMESTAMP,
                        }
                    )
                else:
                    logger.error("No metadata available")
                    doc_ref.update(
                        {
                            "status": "failed",
                            "message": "No metadata available",
                            "error": "Failed to fetch profile data",
                            "timestamp": firestore.SERVER_TIMESTAMP,
                        }
                    )
            except Exception as e:
                logger.error(f"Error during scraping: {str(e)}")
                logger.error(traceback.format_exc())
                doc_ref.update(
                    {
                        "status": "failed",
                        "message": "Error during scraping",
                        "error": str(e),
                        "timestamp": firestore.SERVER_TIMESTAMP,
                    }
                )

        # Start background task
        background_tasks.add_task(process_scraping)

        return {"message": "Scraping started", "username": request.username}

    except Exception as e:
        logger.error(f"Error in scrape_profile endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/process-ai")
async def process_ai(request: ProcessAIRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"Starting AI processing for username: {request.username}")
        # Initialize scraper
        api_key = os.getenv("RAPIDAPI_KEY")
        if not api_key:
            logger.error("API key not configured")
            raise HTTPException(status_code=500, detail="API key not configured")

        # Check gcloud authentication and setup
        if not check_gcloud_auth():
            logger.error("Google Cloud authentication not configured")
            raise HTTPException(
                status_code=500,
                detail="Google Cloud authentication not configured. Please run 'gcloud auth application-default login'",
            )

        # Setup Vertex AI and get project ID
        project_id = setup_vertex_ai()
        if not project_id:
            logger.error("Failed to set up Vertex AI")
            raise HTTPException(
                status_code=500,
                detail="Failed to set up Vertex AI. Please check your Google Cloud configuration.",
            )

        logger.info(f"Using project ID: {project_id}")

        # Initialize scraper with project ID
        scraper = InstagramScraper(api_key, project_id=project_id)

        # Initialize status in Firestore
        doc_ref = db.collection("scraping_results").document(request.username)

        # First, check if the document exists and has metadata
        doc = doc_ref.get()
        if not doc.exists:
            logger.error(f"Document for {request.username} does not exist")
            raise HTTPException(
                status_code=404, detail=f"Document for {request.username} not found"
            )

        existing_data = doc.to_dict()
        existing_metadata = existing_data.get("metadata", [])
        logger.info(
            f"Initial check - Existing metadata length: {len(existing_metadata)}"
        )

        if len(existing_metadata) == 0:
            logger.warning(
                f"Document for {request.username} has empty metadata array. This might cause issues."
            )

        # Update status to initializing
        doc_ref.update(
            {
                "status": "initializing",
                "timestamp": firestore.SERVER_TIMESTAMP,
                "message": "Starting AI processing...",
            }
        )

        # Start AI processing in background
        def process_ai_analysis():
            try:
                # Run AI processing with the specified processing option
                logger.info(
                    f"Running AI processing with option: {request.processing_option}"
                )
                metadata_df = scraper.run_ai_processing(
                    request.username, processing_option=request.processing_option
                )

                if metadata_df is not None:
                    # Log the DataFrame info
                    logger.info(f"Metadata DataFrame shape: {metadata_df.shape}")
                    logger.info(
                        f"Metadata DataFrame columns: {metadata_df.columns.tolist()}"
                    )

                    # Check if AI fields are present
                    ai_fields = [
                        "ai_analysis",
                        "ai_content_description",
                        "ai_processed_time",
                        "ai_analysis_results",
                    ]
                    for field in ai_fields:
                        if field in metadata_df.columns:
                            non_empty = metadata_df[field].notna().sum()
                            logger.info(
                                f"Non-empty {field} values: {non_empty}/{len(metadata_df)}"
                            )
                        else:
                            logger.warning(f"Field {field} not found in DataFrame")

                    # Convert metadata to dict for Firestore
                    logger.debug("Converting metadata DataFrame to dictionary")
                    metadata_dict = metadata_df.to_dict(orient="records")
                    logger.info(f"Metadata dictionary length: {len(metadata_dict)}")

                    # Convert NumPy arrays to lists for Firestore compatibility
                    logger.debug("Converting data to Firestore compatible format")
                    firestore_compatible_metadata = convert_to_firestore_compatible(
                        metadata_dict
                    )
                    logger.info(
                        f"Firestore compatible metadata length: {len(firestore_compatible_metadata)}"
                    )

                    # Store in Firestore
                    doc_ref = db.collection("scraping_results").document(
                        request.username
                    )

                    # Get existing document again to ensure we have the latest data
                    doc = doc_ref.get()
                    if doc.exists:
                        existing_data = doc.to_dict()
                        existing_metadata = existing_data.get("metadata", [])
                        logger.info(
                            f"Existing metadata length: {len(existing_metadata)}"
                        )

                        # Log the first few post IDs in existing metadata
                        if existing_metadata:
                            logger.info(
                                f"First few post IDs in existing metadata: {[post.get('post_id', 'N/A') for post in existing_metadata[:5]]}"
                            )

                        # Log the first few post IDs in new metadata
                        if firestore_compatible_metadata:
                            logger.info(
                                f"First few post IDs in new metadata: {[post.get('post_id', 'N/A') for post in firestore_compatible_metadata[:5]]}"
                            )

                        # If existing metadata is empty, use the new metadata directly
                        if (
                            len(existing_metadata) == 0
                            and len(firestore_compatible_metadata) > 0
                        ):
                            logger.info(
                                "Existing metadata is empty. Using new metadata directly."
                            )
                            doc_ref.update(
                                {
                                    "metadata": firestore_compatible_metadata,
                                    "status": "completed",
                                    "timestamp": firestore.SERVER_TIMESTAMP,
                                    "message": f"Successfully added {len(firestore_compatible_metadata)} posts with AI analysis",
                                }
                            )
                            return

                        # Update metadata based on processing option
                        if request.processing_option == "update_all":
                            logger.info(
                                f"Updating all posts with new AI analysis. Found {len(firestore_compatible_metadata)} posts in parquet file"
                            )

                            # CRITICAL FIX: If existing_metadata is empty but firestore_compatible_metadata has data,
                            # use the firestore_compatible_metadata directly instead of trying to match
                            if (
                                len(existing_metadata) == 0
                                and len(firestore_compatible_metadata) > 0
                            ):
                                logger.info(
                                    "Existing metadata is empty but new metadata has data. Using new metadata directly."
                                )
                                doc_ref.update(
                                    {
                                        "metadata": firestore_compatible_metadata,
                                        "status": "completed",
                                        "timestamp": firestore.SERVER_TIMESTAMP,
                                        "message": f"Successfully added {len(firestore_compatible_metadata)} posts with AI analysis",
                                    }
                                )
                                return

                            # Update all posts with new AI analysis
                            updated_metadata = []
                            for new_post in firestore_compatible_metadata:
                                # Find matching existing post
                                existing_post = next(
                                    (
                                        p
                                        for p in existing_metadata
                                        if p["post_id"] == new_post["post_id"]
                                    ),
                                    None,
                                )
                                if existing_post:
                                    # Create a copy of existing post to preserve non-AI fields
                                    updated_post = existing_post.copy()
                                    # Update all AI-related fields from parquet file
                                    updated_post["ai_analysis"] = new_post.get(
                                        "ai_analysis", {}
                                    )
                                    updated_post["ai_content_description"] = (
                                        new_post.get("ai_content_description", "")
                                    )
                                    updated_post["ai_processed_time"] = new_post.get(
                                        "ai_processed_time"
                                    )
                                    updated_post["ai_analysis_results"] = new_post.get(
                                        "ai_analysis_results", {}
                                    )
                                    logger.debug(
                                        f"Updating post {new_post.get('post_id')} with new AI analysis"
                                    )
                                    updated_metadata.append(updated_post)
                                else:
                                    logger.warning(
                                        f"Could not find matching post for post_id {new_post.get('post_id')}"
                                    )
                                    # CRITICAL FIX: If we can't find a matching post, add the new post to the updated metadata
                                    logger.info(
                                        f"Adding new post {new_post.get('post_id')} to metadata"
                                    )
                                    updated_metadata.append(new_post)

                            # CRITICAL FIX: If no posts were updated but we have new metadata, use the new metadata
                            if (
                                len(updated_metadata) == 0
                                and len(firestore_compatible_metadata) > 0
                            ):
                                logger.warning(
                                    "No posts were updated but we have new metadata. Using new metadata directly."
                                )
                                updated_metadata = firestore_compatible_metadata

                            # Update Firestore with complete metadata array
                            logger.info(
                                f"Updating Firestore with {len(updated_metadata)} processed posts"
                            )

                            # CRITICAL FIX: Ensure we're not updating with an empty array
                            if len(updated_metadata) == 0:
                                logger.error(
                                    "Attempting to update Firestore with empty metadata array. Aborting update."
                                )
                                doc_ref.update(
                                    {
                                        "status": "failed",
                                        "timestamp": firestore.SERVER_TIMESTAMP,
                                        "error": "Failed to update metadata: Empty metadata array",
                                    }
                                )
                                return

                            doc_ref.update(
                                {
                                    "metadata": updated_metadata,
                                    "status": "completed",
                                    "timestamp": firestore.SERVER_TIMESTAMP,
                                    "message": f"Successfully updated {len(updated_metadata)} posts with AI analysis",
                                }
                            )
                        elif request.processing_option == "update_remaining":
                            # Update only posts without AI analysis
                            updated_count = 0
                            posts_without_ai = []
                            posts_with_ai = []

                            # CRITICAL FIX: If existing_metadata is empty but firestore_compatible_metadata has data,
                            # use the firestore_compatible_metadata directly
                            if (
                                len(existing_metadata) == 0
                                and len(firestore_compatible_metadata) > 0
                            ):
                                logger.info(
                                    "Existing metadata is empty but new metadata has data. Using new metadata directly."
                                )
                                doc_ref.update(
                                    {
                                        "metadata": firestore_compatible_metadata,
                                        "status": "completed",
                                        "timestamp": firestore.SERVER_TIMESTAMP,
                                        "message": f"Successfully added {len(firestore_compatible_metadata)} posts with AI analysis",
                                    }
                                )
                                return

                            # First, correctly identify posts with and without AI analysis
                            for post in existing_metadata:
                                # Check if post has ai_analysis_results and if it contains a description field
                                if post.get("ai_analysis_results") and post.get(
                                    "ai_analysis_results", {}
                                ).get("description"):
                                    posts_with_ai.append(post.get("post_id", "N/A"))
                                else:
                                    posts_without_ai.append(post.get("post_id", "N/A"))

                            logger.info(
                                f"Initial state - Posts without AI analysis: {posts_without_ai}"
                            )
                            logger.info(
                                f"Initial state - Posts with AI analysis: {posts_with_ai}"
                            )

                            # Now process posts without AI analysis
                            for post in existing_metadata:
                                # Check if post has ai_analysis_results and if it contains a description field
                                if not (
                                    post.get("ai_analysis_results")
                                    and post.get("ai_analysis_results", {}).get(
                                        "description"
                                    )
                                ):
                                    # Find matching new metadata
                                    new_data = next(
                                        (
                                            item
                                            for item in firestore_compatible_metadata
                                            if item["post_id"] == post["post_id"]
                                        ),
                                        None,
                                    )
                                    # Check if new_data has meaningful AI analysis results with description
                                    if (
                                        new_data
                                        and "ai_analysis_results" in new_data
                                        and new_data.get("ai_analysis_results")
                                        and new_data.get("ai_analysis_results", {}).get(
                                            "description"
                                        )
                                    ):
                                        # Log the AI analysis to verify it's meaningful
                                        logger.info(
                                            f"Found meaningful AI analysis for post {post['post_id']}: {new_data.get('ai_analysis_results')}"
                                        )

                                        # Update the correct field names
                                        post["ai_analysis_results"] = new_data[
                                            "ai_analysis_results"
                                        ]
                                        post["ai_content_description"] = new_data.get(
                                            "ai_content_description", ""
                                        )
                                        post["ai_processed_time"] = new_data.get(
                                            "ai_processed_time"
                                        )
                                        updated_count += 1
                                        logger.info(
                                            f"Updated post {post['post_id']} with AI analysis"
                                        )
                                    elif new_data:
                                        logger.warning(
                                            f"Post {post['post_id']} has matching data but no meaningful AI analysis results with description"
                                        )
                                    else:
                                        logger.warning(
                                            f"No matching data found for post {post['post_id']}"
                                        )

                            # Recalculate posts with and without AI analysis after updates
                            posts_without_ai = []
                            posts_with_ai = []
                            for post in existing_metadata:
                                # Check if post has ai_analysis_results and if it contains a description field
                                if post.get("ai_analysis_results") and post.get(
                                    "ai_analysis_results", {}
                                ).get("description"):
                                    posts_with_ai.append(post.get("post_id", "N/A"))
                                else:
                                    posts_without_ai.append(post.get("post_id", "N/A"))

                            logger.info(
                                f"Updated {updated_count} posts with AI analysis"
                            )
                            logger.info(
                                f"Posts without AI analysis: {posts_without_ai}"
                            )
                            logger.info(f"Posts with AI analysis: {posts_with_ai}")

                            # Check if any posts were updated
                            if updated_count == 0:
                                logger.warning(
                                    "No posts were updated. All posts might already have AI analysis."
                                )
                                # Check if all posts already have AI analysis with description
                                all_have_ai = all(
                                    post.get("ai_analysis_results")
                                    and post.get("ai_analysis_results", {}).get(
                                        "description"
                                    )
                                    for post in existing_metadata
                                )
                                if all_have_ai:
                                    logger.info(
                                        "All posts already have AI analysis with description."
                                    )
                                else:
                                    logger.warning(
                                        "Some posts don't have AI analysis with description but weren't updated."
                                    )
                                    # Log the post IDs in the new metadata
                                    new_post_ids = [
                                        post["post_id"]
                                        for post in firestore_compatible_metadata
                                    ]
                                    logger.warning(
                                        f"Posts in new metadata: {new_post_ids}"
                                    )

                                    # Check if there's a mismatch between existing and new metadata
                                    existing_post_ids = [
                                        post.get("post_id", "N/A")
                                        for post in existing_metadata
                                    ]
                                    new_post_ids = [
                                        post.get("post_id", "N/A")
                                        for post in firestore_compatible_metadata
                                    ]

                                    # Find posts in existing metadata but not in new metadata
                                    missing_in_new = [
                                        pid
                                        for pid in existing_post_ids
                                        if pid not in new_post_ids
                                    ]
                                    logger.warning(
                                        f"Posts in existing metadata but not in new metadata: {missing_in_new}"
                                    )

                                    # Find posts in new metadata but not in existing metadata
                                    missing_in_existing = [
                                        pid
                                        for pid in new_post_ids
                                        if pid not in existing_post_ids
                                    ]
                                    logger.warning(
                                        f"Posts in new metadata but not in existing metadata: {missing_in_existing}"
                                    )

                                    # If no posts were updated but some don't have AI analysis, use the new metadata
                                    if len(firestore_compatible_metadata) > 0:
                                        logger.info(
                                            "Using new metadata from AI processing."
                                        )
                                        existing_metadata = (
                                            firestore_compatible_metadata
                                        )

                            # Log the metadata before updating Firestore
                            logger.info(
                                f"Metadata length before Firestore update: {len(existing_metadata)}"
                            )
                            if existing_metadata:
                                logger.info(
                                    f"First post in metadata before update: {existing_metadata[0].get('post_id', 'N/A')}"
                                )
                                logger.info(
                                    f"AI fields in first post: ai_analysis_results={bool(existing_metadata[0].get('ai_analysis_results'))}, ai_content_description={bool(existing_metadata[0].get('ai_content_description'))}"
                                )

                            # CRITICAL FIX: Ensure we're not updating with an empty array
                            if len(existing_metadata) == 0:
                                logger.error(
                                    "Attempting to update Firestore with empty metadata array. Aborting update."
                                )
                                doc_ref.update(
                                    {
                                        "status": "failed",
                                        "timestamp": firestore.SERVER_TIMESTAMP,
                                        "error": "Failed to update metadata: Empty metadata array",
                                    }
                                )
                                return

                            doc_ref.update(
                                {
                                    "metadata": existing_metadata,
                                    "status": "completed",
                                    "timestamp": firestore.SERVER_TIMESTAMP,
                                    "message": f"Successfully updated {updated_count} posts with AI analysis",
                                }
                            )

                            # Verify the update
                            updated_doc = doc_ref.get()
                            if updated_doc.exists:
                                updated_data = updated_doc.to_dict()
                                updated_metadata = updated_data.get("metadata", [])
                                logger.info(
                                    f"Metadata length after Firestore update: {len(updated_metadata)}"
                                )
                                if updated_metadata:
                                    logger.info(
                                        f"First post in metadata after update: {updated_metadata[0].get('post_id', 'N/A')}"
                                    )
                                    logger.info(
                                        f"AI fields in first post: ai_analysis_results={bool(updated_metadata[0].get('ai_analysis_results'))}, ai_content_description={bool(updated_metadata[0].get('ai_content_description'))}"
                                    )
                        else:  # skip
                            doc_ref.update(
                                {
                                    "status": "completed",
                                    "timestamp": firestore.SERVER_TIMESTAMP,
                                    "message": "AI processing skipped",
                                }
                            )
                    else:
                        logger.error("Original scraping data not found")
                        doc_ref.set(
                            {
                                "status": "failed",
                                "timestamp": firestore.SERVER_TIMESTAMP,
                                "error": "Original scraping data not found",
                            }
                        )
                else:
                    logger.error("AI processing failed - no data returned")
                    doc_ref = db.collection("scraping_results").document(
                        request.username
                    )
                    doc_ref.update(
                        {
                            "status": "failed",
                            "timestamp": firestore.SERVER_TIMESTAMP,
                            "error": "AI processing failed - no data returned",
                        }
                    )
            except Exception as e:
                logger.error(f"Error during AI processing: {str(e)}")
                logger.error(traceback.format_exc())
                doc_ref = db.collection("scraping_results").document(request.username)
                doc_ref.update(
                    {
                        "status": "failed",
                        "timestamp": firestore.SERVER_TIMESTAMP,
                        "error": str(e),
                    }
                )

        # Start background task
        background_tasks.add_task(process_ai_analysis)

        return {"message": "AI processing started", "username": request.username}

    except Exception as e:
        logger.error(f"Error in process_ai endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/verify")
async def verify_metadata(request: VerifyRequest, background_tasks: BackgroundTasks):
    try:
        # Initialize scraper
        api_key = os.getenv("RAPIDAPI_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="API key not configured")

        # Check gcloud authentication and setup
        if not check_gcloud_auth():
            raise HTTPException(
                status_code=500,
                detail="Google Cloud authentication not configured. Please run 'gcloud auth application-default login'",
            )

        # Setup Vertex AI and get project ID
        project_id = setup_vertex_ai()
        if not project_id:
            raise HTTPException(
                status_code=500,
                detail="Failed to set up Vertex AI. Please check your Google Cloud configuration.",
            )

        # Initialize scraper with project ID
        scraper = InstagramScraper(api_key, project_id=project_id)

        # Initialize status in Firestore
        doc_ref = db.collection("verification_results").document(request.username)
        doc_ref.set(
            {
                "status": "initializing",
                "timestamp": firestore.SERVER_TIMESTAMP,
                "message": "Starting metadata verification...",
            }
        )

        # Start verification in background
        def process_verification():
            try:
                # Run metadata verification
                metadata_df = scraper.verify_metadata_integrity(request.username)

                if metadata_df is not None:
                    # Convert metadata to dict for Firestore
                    metadata_dict = metadata_df.to_dict(orient="records")

                    # Store in Firestore
                    doc_ref = db.collection("verification_results").document(
                        request.username
                    )

                    # Update Firestore with verification results
                    doc_ref.update(
                        {
                            "status": "completed",
                            "timestamp": firestore.SERVER_TIMESTAMP,
                            "message": f"Successfully verified metadata for {request.username}",
                            "metadata": metadata_dict,
                        }
                    )
                else:
                    doc_ref = db.collection("verification_results").document(
                        request.username
                    )
                    doc_ref.update(
                        {
                            "status": "failed",
                            "timestamp": firestore.SERVER_TIMESTAMP,
                            "error": "Metadata verification failed - no data returned",
                        }
                    )
            except Exception as e:
                doc_ref = db.collection("verification_results").document(
                    request.username
                )
                doc_ref.update(
                    {
                        "status": "failed",
                        "timestamp": firestore.SERVER_TIMESTAMP,
                        "error": str(e),
                    }
                )

        # Start background task
        background_tasks.add_task(process_verification)

        return {
            "message": "Metadata verification started",
            "username": request.username,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/status/{username}")
async def get_status(username: str):
    try:
        # Check scraping status
        scraping_doc = db.collection("scraping_results").document(username).get()
        scraping_data = scraping_doc.to_dict() if scraping_doc.exists else None

        # Check AI processing status
        ai_doc = db.collection("scraping_results").document(username).get()
        ai_data = ai_doc.to_dict() if ai_doc.exists else None

        # Create detailed status response
        scraping_status = ScrapeStatus(
            status="not_started"
            if not scraping_data
            else scraping_data.get("status", "not_started"),
            total_posts=scraping_data.get("total_posts") if scraping_data else None,
            current_post=scraping_data.get("current_post") if scraping_data else None,
            profile_name=username,
            message=scraping_data.get("message") if scraping_data else None,
            error=scraping_data.get("error") if scraping_data else None,
        )

        ai_status = ScrapeStatus(
            status="not_started"
            if not ai_data
            else ai_data.get("status", "not_started"),
            message=ai_data.get("message") if ai_data else None,
            error=ai_data.get("error") if ai_data else None,
        )

        return ProcessingStatus(scraping=scraping_status, ai_processing=ai_status)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/verify-status/{username}")
async def get_verify_status(username: str):
    try:
        # Check verification status
        verify_doc = db.collection("verification_results").document(username).get()
        verify_data = verify_doc.to_dict() if verify_doc.exists else None

        # Create detailed status response
        verify_status = VerifyStatus(
            status="not_started"
            if not verify_data
            else verify_data.get("status", "not_started"),
            message=verify_data.get("message") if verify_data else None,
            error=verify_data.get("error") if verify_data else None,
        )

        return verify_status

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def send_instagram_message(recipient_id: str, message: str) -> dict:
    """
    Send a message to an Instagram user using the Instagram Graph API.

    Args:
        recipient_id: The Instagram ID of the message recipient
        message: The message text to send

    Returns:
        dict: The API response
    """
    try:
        logger.info(f"Preparing to send Instagram message to recipient: {recipient_id}")
        logger.debug(f"Message content: {message[:100]}...")

        instagram_token = os.getenv("INSTAGRAM_USER_ACCESS_TOKEN")
        if not instagram_token:
            logger.error(
                "INSTAGRAM_USER_ACCESS_TOKEN not found in environment variables"
            )
            raise ValueError(
                "INSTAGRAM_USER_ACCESS_TOKEN not found in environment variables"
            )

        sender_id = os.getenv("INSTAGRAM_SENDER_ID")
        if not sender_id:
            logger.error("INSTAGRAM_SENDER_ID not found in environment variables")
            raise ValueError("INSTAGRAM_SENDER_ID not found in environment variables")

        url = f"https://graph.instagram.com/v22.0/{sender_id}/messages"
        headers = {
            "Authorization": f"Bearer {instagram_token}",
            "Content-Type": "application/json",
        }

        # Format the message to ensure links are properly recognized
        # Instagram will automatically detect URLs in the message
        data = {"recipient": {"id": recipient_id}, "message": {"text": message}}

        logger.info(f"Sending request to Instagram API: {url}")
        logger.debug(f"Request headers: {headers}")
        logger.debug(f"Request data: {data}")

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            response_data = response.json()
            logger.info(f"Instagram API response: {response_data}")

            # Add a small delay to avoid rate limiting
            await asyncio.sleep(1)

            return response_data

    except Exception as e:
        logger.error(f"Error sending Instagram message: {str(e)}")
        logger.error(traceback.format_exc())
        raise


def generate_gemini_response(results: List[Dict[str, Any]], query: str) -> List[str]:
    """
    Generate a response using Google Gemini 2.0 Flash based on search results.

    Args:
        results: List of search results from RAG retrieval
        query: The original search query

    Returns:
        List[str]: A list of messages to send, with the first being an introduction
                  and subsequent messages containing individual links
    """
    try:
        logger.info(
            f"Generating Gemini response for query: '{query}' with {len(results)} results"
        )

        # Initialize Vertex AI
        project_id = os.getenv("FIREBASE_PROJECT_ID")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        logger.info(
            f"Initializing Vertex AI with project_id: {project_id}, location: {location}"
        )
        aiplatform.init(project=project_id, location=location)

        # Initialize Gemini model
        logger.info("Initializing Gemini 2.0 Flash model")
        model = GenerativeModel("gemini-1.5-flash-002")

        # Group results by username
        logger.info("Grouping search results by username")
        grouped_results = {}
        for result in results:
            username = result.get("username", "Unknown")
            if username not in grouped_results:
                grouped_results[username] = []
            grouped_results[username].append(result)

        logger.info(f"Grouped results by {len(grouped_results)} usernames")

        # Create a prompt for Gemini to generate an introduction message
        logger.info("Creating prompt for Gemini introduction message")
        intro_prompt = f"""
        I searched for "{query}" and found the following Instagram posts. 
        Please create a very short, friendly introduction message (max 50 characters) 
        that tells the user I found posts matching their criteria.
        
        Here are the search results:
        {json.dumps(grouped_results, indent=2)}
        """

        logger.debug(f"Gemini intro prompt: {intro_prompt[:500]}...")

        # Generate introduction with Gemini
        logger.info("Generating introduction with Gemini")
        intro_response = model.generate_content(intro_prompt)

        # Extract the text from the response
        intro_text = intro_response.text
        logger.info(f"Generated introduction: {intro_text}")

        # Filter results by relevance score
        high_relevance_results = [r for r in results if r.get("score", 0) > 0.8]
        logger.info(
            f"Found {len(high_relevance_results)} results with relevance score > 0.8"
        )

        # If no high relevance results, take top 2
        if not high_relevance_results and results:
            logger.info("No high relevance results, taking top 2 results")
            high_relevance_results = sorted(
                results, key=lambda x: x.get("score", 0), reverse=True
            )[:2]

        # Create messages for each result
        messages = [intro_text]

        for result in high_relevance_results:
            username = result.get("username", "Unknown")
            post_url = result.get("post_url", "")
            caption = (
                result.get("caption", "")[:50] + "..."
                if result.get("caption")
                else "No caption"
            )

            # Create a message for each result
            result_message = f"{username}: {post_url}"
            messages.append(result_message)
            logger.info(f"Added message for {username}: {post_url[:30]}...")

        logger.info(f"Generated {len(messages)} messages in total")
        return messages

    except Exception as e:
        logger.error(f"Error generating Gemini response: {str(e)}")
        logger.error(traceback.format_exc())
        # Fallback to a simple response if Gemini fails
        fallback_response = [
            f"Found {len(results)} results for '{query}'. Check the app for details."
        ]
        logger.info(f"Using fallback response: {fallback_response[0]}")
        return fallback_response


@app.post("/api/search")
async def search_posts(request: SearchRequest):
    try:
        logger.info(
            f"Searching posts with query: '{request.query}', top_k: {request.top_k}, recipient_id: {request.instagram_recipient_id}"
        )
        search_service = SearchService()
        results = search_service.search_posts(request.query, top_k=request.top_k)
        logger.info(f"Search returned {len(results)} results")

        # Generate a response using Gemini
        if results:
            logger.info("Generating response with Gemini for search results")
            messages = generate_gemini_response(results, request.query)
            logger.info(f"Generated {len(messages)} messages")
        else:
            logger.warning(f"No results found for query: '{request.query}'")
            messages = [f"No results found for: {request.query}"]

        # Send the messages to Instagram
        try:
            logger.info(
                f"Sending {len(messages)} messages to Instagram recipient: {request.instagram_recipient_id}"
            )

            # Send each message with a small delay between them
            for i, message in enumerate(messages):
                logger.info(f"Sending message {i + 1}/{len(messages)}")
                await send_instagram_message(request.instagram_recipient_id, message)

                # Add a small delay between messages (except for the last one)
                if i < len(messages) - 1:
                    await asyncio.sleep(1)

            logger.info("All messages sent successfully")
            return {
                "results": results,
                "messages_sent": True,
                "message_count": len(messages),
            }
        except Exception as e:
            logger.error(f"Error sending Instagram messages: {str(e)}")
            logger.error(traceback.format_exc())
            return {"results": results, "messages_sent": False, "error": str(e)}

    except Exception as e:
        logger.error(f"Error searching posts: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    logger.info("API Service starting up...")

    # Initialize Firebase
    cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    logger.info(f"Firebase initialized with credentials from file: {cred_path}")

    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=8080)
