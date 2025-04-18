#!/usr/bin/env python3
import argparse
import os
import subprocess
from dotenv import load_dotenv
from .scrapers.instagram_scraper import InstagramScraper


def check_gcloud_auth():
    """Check if gcloud is authenticated and configured correctly"""
    try:
        # First check if we're in a Docker container
        is_docker = os.path.exists("/.dockerenv")

        # Check for service account credentials
        creds_paths = [
            # Docker container paths
            "/app/credentials/service-account.json",
            "/app/credentials/instagram-scraper-service-account.json",
            # Local paths
            os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "credentials",
                "service-account.json",
            ),
            os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
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
                print(f"Using Google Cloud credentials from: {path}")
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
                return True

        # If we're in Docker, we can't use gcloud CLI
        if is_docker:
            print("Running in Docker but no service account credentials found.")
            print("Please ensure one of the following files exists:")
            for path in creds_paths:
                print(f"  - {path}")
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
                print("Application Default Credentials not found. Please run:")
                print("gcloud auth application-default login")
                return False

            # Check if project ID is set
            result = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True,
                text=True,
            )
            if not result.stdout.strip():
                print("No default project set. Please run:")
                print("gcloud config set project YOUR_PROJECT_ID")
                return False

            return True
        except subprocess.CalledProcessError:
            print("gcloud CLI not found. Please install the Google Cloud CLI:")
            print("https://cloud.google.com/sdk/docs/install")
            return False
    except Exception as e:
        print(f"Error checking Google Cloud authentication: {str(e)}")
        return False


def setup_vertex_ai():
    """Ensure Vertex AI is properly set up"""
    try:
        # Check if we're in a Docker container
        is_docker = os.path.exists("/.dockerenv")

        # Get project ID from service account file if available
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path and os.path.exists(creds_path):
            try:
                import json

                with open(creds_path, "r") as f:
                    creds_data = json.load(f)
                    project_id = creds_data.get("project_id")
                    if project_id:
                        print(f"Using project ID from service account: {project_id}")
                        return project_id
            except Exception as e:
                print(f"Error reading project ID from service account: {str(e)}")

        # If we're in Docker, we can't use gcloud CLI
        if is_docker:
            print("Running in Docker but couldn't determine project ID.")
            print(
                "Please ensure GOOGLE_APPLICATION_CREDENTIALS is set to a valid service account file."
            )
            return None

        # For local development, try gcloud CLI
        try:
            # Get project ID from gcloud config
            result = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True,
                text=True,
            )
            project_id = result.stdout.strip()

            # Check if Vertex AI API is enabled
            services = subprocess.run(
                ["gcloud", "services", "list", "--format=value(NAME)"],
                capture_output=True,
                text=True,
            ).stdout

            if "aiplatform.googleapis.com" not in services:
                print("Enabling Vertex AI API...")
                subprocess.run(
                    ["gcloud", "services", "enable", "aiplatform.googleapis.com"],
                    check=True,
                )
                print("Vertex AI API enabled successfully")

            return project_id
        except subprocess.CalledProcessError as e:
            print(f"Error setting up Vertex AI: {str(e)}")
            return None
    except Exception as e:
        print(f"Error in setup_vertex_ai: {str(e)}")
        return None


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Instagram Media Scraper and AI Processor"
    )
    parser.add_argument(
        "--username", "-u", required=True, help="Instagram username to process"
    )
    parser.add_argument(
        "--max-posts",
        "-m",
        type=int,
        default=50,
        help="Maximum number of posts to scrape (default: 50)",
    )
    parser.add_argument(
        "--mode",
        "-M",
        choices=["scrape", "ai", "verify"],
        required=True,
        help='Mode: "scrape" for scraping posts, "ai" for running AI processing, "verify" for verifying metadata integrity',
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Get API key from environment variable
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        print("Error: RAPIDAPI_KEY not found in .env file")
        return

    # Check gcloud authentication and setup
    if not check_gcloud_auth():
        return

    # Setup Vertex AI and get project ID
    project_id = setup_vertex_ai()
    if not project_id:
        return

    print(f"\nUsing Google Cloud Project: {project_id}")

    # Initialize scraper with project ID
    scraper = InstagramScraper(api_key, project_id=project_id)

    # Run the selected pipeline
    if args.mode == "scrape":
        print(f"\nStarting scraping pipeline for user: {args.username}")
        print(f"Maximum posts to scrape: {args.max_posts}")
        metadata_df = scraper.process_profile(args.username, args.max_posts)
        if metadata_df is not None:
            print("\nScraping pipeline completed successfully")
    elif args.mode == "ai":
        print(f"\nStarting AI processing pipeline for user: {args.username}")
        metadata_df = scraper.run_ai_processing(args.username)
        if metadata_df is not None:
            print("\nAI processing pipeline completed successfully")
    else:  # mode == 'verify'
        print(f"\nStarting metadata verification for user: {args.username}")
        metadata_df = scraper.verify_metadata_integrity(args.username)
        if metadata_df is not None:
            print("\nMetadata verification completed successfully")


if __name__ == "__main__":
    main()
