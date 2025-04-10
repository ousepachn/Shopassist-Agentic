from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from dotenv import load_dotenv
from instagram_scraper import InstagramScraper
import firebase_admin
from firebase_admin import credentials, firestore
import json
import subprocess
import logging
import numpy as np
import traceback

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

# Initialize Firebase Admin
cred = credentials.Certificate(os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH"))
firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this with your Next.js app's domain in production
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


def check_gcloud_auth():
    """Check if gcloud is authenticated and configured correctly"""
    try:
        # Check if gcloud is installed
        subprocess.run(["gcloud", "--version"], check=True, capture_output=True)

        # Check if application-default credentials exist
        credentials_path = os.path.expanduser(
            "~/.config/gcloud/application_default_credentials.json"
        )
        if not os.path.exists(credentials_path):
            return False

        # Check if project ID is set
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"], capture_output=True, text=True
        )
        if not result.stdout.strip():
            return False

        return True
    except subprocess.CalledProcessError:
        return False


def setup_vertex_ai():
    """Ensure Vertex AI is properly set up"""
    try:
        # Get project ID from gcloud config
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"], capture_output=True, text=True
        )
        project_id = result.stdout.strip()

        # Check if Vertex AI API is enabled
        services = subprocess.run(
            ["gcloud", "services", "list", "--format=value(NAME)"],
            capture_output=True,
            text=True,
        ).stdout

        if "aiplatform.googleapis.com" not in services:
            subprocess.run(
                ["gcloud", "services", "enable", "aiplatform.googleapis.com"],
                check=True,
            )

        return project_id
    except subprocess.CalledProcessError:
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
        doc_ref.set(
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
                    # Convert metadata to dict for Firestore
                    logger.debug("Converting metadata DataFrame to dictionary")
                    metadata_dict = metadata_df.to_dict(orient="records")

                    # Convert NumPy arrays to lists for Firestore compatibility
                    logger.debug("Converting data to Firestore compatible format")
                    firestore_compatible_metadata = convert_to_firestore_compatible(
                        metadata_dict
                    )

                    # Store in Firestore
                    doc_ref = db.collection("scraping_results").document(
                        request.username
                    )

                    # Get existing document
                    doc = doc_ref.get()
                    if doc.exists:
                        existing_data = doc.to_dict()
                        existing_metadata = existing_data.get("metadata", [])

                        # Update metadata based on processing option
                        if request.processing_option == "update_all":
                            logger.info(
                                f"Updating all posts with new AI analysis. Found {len(firestore_compatible_metadata)} posts in parquet file"
                            )
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

                            # Update Firestore with complete metadata array
                            logger.info(
                                f"Updating Firestore with {len(updated_metadata)} processed posts"
                            )
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
                            for post in existing_metadata:
                                if not post.get("ai_analysis"):
                                    # Find matching new metadata
                                    new_data = next(
                                        (
                                            item
                                            for item in firestore_compatible_metadata
                                            if item["post_id"] == post["post_id"]
                                        ),
                                        None,
                                    )
                                    if new_data and "ai_analysis" in new_data:
                                        post["ai_analysis"] = new_data["ai_analysis"]
                                        post["ai_content_description"] = new_data.get(
                                            "ai_content_description", ""
                                        )
                                        post["ai_processed_time"] = new_data.get(
                                            "ai_processed_time"
                                        )
                                        post["ai_analysis_results"] = new_data.get(
                                            "ai_analysis_results", {}
                                        )

                            doc_ref.update(
                                {
                                    "metadata": existing_metadata,
                                    "status": "completed",
                                    "timestamp": firestore.SERVER_TIMESTAMP,
                                    "message": "Successfully updated remaining posts with AI analysis",
                                }
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
