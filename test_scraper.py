import os
from instagram_scraper import InstagramScraper
from update_firestore import update_firestore_metadata
import pandas as pd


def test_scraping_pipeline():
    """Test the entire scraping pipeline"""
    print("\n[TEST] Step 1: Testing metadata creation...")

    # Initialize scraper
    username = "whatsmitafound"
    max_posts = 5
    scraper = InstagramScraper(auto_process_with_vertex=False)

    # Get metadata
    metadata = scraper.process_profile(username, max_posts)

    if metadata is None:
        print("Failed to create metadata DataFrame")
        return

    # Create metadata directory if it doesn't exist
    os.makedirs(f"instagram/{username}", exist_ok=True)

    # Save metadata to parquet
    metadata_path = f"instagram/{username}/metadata.parquet"
    metadata.to_parquet(metadata_path)

    print("\nMetadata DataFrame Info:")
    print(metadata.info())
    print("\nTimestamp values:")
    for idx, row in metadata.iterrows():
        print(
            f"Post {row['post_id']}: {row['timestamp']} (type: {type(row['timestamp'])})"
        )
    print("\nSample Data:")
    print(
        metadata[
            ["post_id", "timestamp", "media_type", "media_urls", "gcs_location"]
        ].head()
    )

    print("\n[TEST] Step 2: Testing media download...")
    # Media download is handled in process_profile

    print("\n[TEST] Step 3: Testing Firestore update...")
    # Verify metadata file exists
    if not os.path.exists(metadata_path):
        print(f"Error: Metadata file not found at {metadata_path}")
        return

    update_firestore_metadata(metadata_path)


if __name__ == "__main__":
    test_scraping_pipeline()
