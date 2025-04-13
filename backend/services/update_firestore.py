import os
from google.cloud import firestore
from dotenv import load_dotenv
from scrapers.instagram_scraper import CloudStorageHandler
import numpy as np
import pandas as pd
from datetime import datetime
import json
import traceback


def convert_media_urls(media_urls):
    """Helper function to convert media_urls to a list of strings"""
    if isinstance(media_urls, np.ndarray):
        return [str(url) for url in media_urls]
    elif isinstance(media_urls, str):
        return [str(media_urls)]
    elif isinstance(media_urls, list):
        return [str(url) for url in media_urls]
    else:
        print(f"[WARNING] Unexpected media_urls type: {type(media_urls)}")
        return []


def update_firestore_metadata(metadata_path):
    """Update Firestore with metadata from the parquet file."""
    print(f"Loading metadata from {metadata_path}...")

    # Read metadata from parquet file
    df = pd.read_parquet(metadata_path)
    if df.empty:
        print("No metadata found in parquet file")
        return

    # Get profile name from first row
    profile_name = df.iloc[0]["username"]

    # Convert DataFrame to list of dictionaries
    posts_data = df.to_dict("records")

    # Initialize Firestore client
    db = firestore.Client()

    # Reference to the profile document
    doc_ref = db.collection("scraping_results").document(profile_name)

    # Get current timestamp
    current_timestamp = datetime.now()

    # Process each post
    processed_posts = []
    for post in posts_data:
        try:
            # Set timestamp to current time if it's empty
            if not post.get("timestamp") or pd.isna(post.get("timestamp")):
                post["timestamp"] = current_timestamp
            elif isinstance(post.get("timestamp"), pd.Timestamp):
                post["timestamp"] = post["timestamp"].to_pydatetime()
            elif isinstance(post.get("timestamp"), str):
                try:
                    post["timestamp"] = pd.to_datetime(
                        post["timestamp"]
                    ).to_pydatetime()
                except:
                    post["timestamp"] = current_timestamp

            # Convert media_urls to list if it's a string or numpy array
            if isinstance(post.get("media_urls"), (str, np.ndarray)):
                post["media_urls"] = (
                    post["media_urls"].tolist()
                    if isinstance(post["media_urls"], np.ndarray)
                    else [post["media_urls"]]
                )

            # Convert vertex_ai fields to lists if they're numpy arrays
            for field in ["vertex_ai_labels", "vertex_ai_objects", "vertex_ai_text"]:
                if isinstance(post.get(field), np.ndarray):
                    post[field] = post[field].tolist()

            # Convert ai_content_description from string to dict if needed
            if isinstance(post.get("ai_content_description"), str):
                try:
                    post["ai_content_description"] = json.loads(
                        post["ai_content_description"]
                    )
                except (json.JSONDecodeError, TypeError):
                    pass  # Keep as string if not valid JSON

            print(f"Successfully processed post {post['post_id']}")
            processed_posts.append(post)

        except Exception as e:
            print(f"Error processing post {post.get('post_id', 'unknown')}: {str(e)}")
            continue

    try:
        # Update Firestore document
        update_data = {
            "profile_name": profile_name,
            "status": "success",
            "message": f"Successfully processed {len(processed_posts)} posts",
            "metadata": processed_posts,
            "total_posts": len(processed_posts),
            "current_post": len(processed_posts),
            "timestamp": current_timestamp,
            "last_updated": firestore.SERVER_TIMESTAMP,
        }

        # Set the document with merge=True to preserve existing fields
        doc_ref.set(update_data, merge=True)
        print(f"Successfully updated Firestore for profile {profile_name}")

    except Exception as e:
        print(f"Error updating Firestore for profile {profile_name}: {str(e)}")
        raise


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        metadata_path = sys.argv[1]
        update_firestore_metadata(metadata_path)
    else:
        print("Please provide a metadata path as argument")
