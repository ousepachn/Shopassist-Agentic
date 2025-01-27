import http.client
import json
import os
import requests
from typing import Dict, List, Optional
import time
from datetime import datetime
import pandas as pd
from tabulate import tabulate
from google.cloud import storage
import io
from media_processor import MediaProcessor
from image_processor import ImageGridProcessor
import numpy as np


class CloudStorageHandler:
    def __init__(self, bucket_name: str):
        """Initialize the Google Cloud Storage client"""
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)

    def upload_file(self, file_data: bytes, destination_blob_name: str) -> str:
        """Upload a file to Google Cloud Storage bucket"""
        blob = self.bucket.blob(destination_blob_name)
        blob.upload_from_string(file_data)
        return blob.public_url

    def upload_dataframe(self, df: pd.DataFrame, destination_blob_name: str):
        """Upload a pandas DataFrame as parquet to Google Cloud Storage bucket"""
        parquet_buffer = io.BytesIO()
        df.to_parquet(parquet_buffer)
        parquet_buffer.seek(0)
        blob = self.bucket.blob(destination_blob_name)
        blob.upload_from_file(parquet_buffer, content_type="application/octet-stream")

    def download_dataframe(self, blob_name: str) -> Optional[pd.DataFrame]:
        """Download and read a parquet file from GCS as DataFrame"""
        try:
            blob = self.bucket.blob(blob_name)
            if not blob.exists():
                return None

            parquet_buffer = io.BytesIO()
            blob.download_to_file(parquet_buffer)
            parquet_buffer.seek(0)
            return pd.read_parquet(parquet_buffer)
        except Exception as e:
            print(f"[ERROR] Failed to download/read parquet file: {str(e)}")
            return None

    def blob_exists(self, blob_name: str) -> bool:
        """Check if a blob exists in the bucket"""
        blob = self.bucket.blob(blob_name)
        return blob.exists()


class InstagramScraper:
    def __init__(
        self,
        api_key: str,
        bucket_name: str = "shopassist-agentic-media-data",
        project_id: str = "shopassist-agentic",
        auto_process_with_vertex: bool = False,
    ):
        """Initialize the scraper with RapidAPI key and GCS bucket"""
        self.api_key = api_key
        self.base_url = "instagram-scraper-api2.p.rapidapi.com"
        self.headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": self.base_url}
        self.cloud_storage = CloudStorageHandler(bucket_name)
        self.media_processor = MediaProcessor(project_id, bucket_name)
        self.image_processor = ImageGridProcessor(bucket_name)
        self.bucket_name = bucket_name
        self.auto_process_with_vertex = auto_process_with_vertex

    def get_user_posts(self, username: str, max_posts: int = 50) -> List[Dict]:
        """Fetch posts for a given username with pagination support"""
        all_posts = []
        pagination_token = None

        try:
            while len(all_posts) < max_posts:
                # Construct URL with pagination token if available
                url = f"/v1.2/posts?username_or_id_or_url={username}"
                if pagination_token:
                    url += f"&pagination_token={pagination_token}"

                print(f"\n[DEBUG] Requesting URL: {url}")
                conn = http.client.HTTPSConnection(self.base_url)
                conn.request("GET", url, headers=self.headers)

                response = conn.getresponse()
                print(f"[DEBUG] Response status: {response.status}")

                response_data = response.read().decode("utf-8")
                print(
                    f"[DEBUG] Raw response: {response_data[:500]}..."
                )  # Print first 500 chars

                data = json.loads(response_data)

                if not data:
                    print("[ERROR] Empty response from API")
                    break

                if "data" not in data:
                    print(
                        f"[ERROR] No 'data' field in response. Response keys: {data.keys()}"
                    )
                    if "error" in data:
                        print(f"[ERROR] API Error: {data['error']}")
                    break

                if "items" not in data["data"]:
                    print(
                        f"[ERROR] No 'items' field in data. Data keys: {data['data'].keys()}"
                    )
                    break

                # Add posts from current page
                posts = data["data"]["items"]
                print(f"[DEBUG] Found {len(posts)} posts in this page")
                all_posts.extend(posts)

                # Check for next page using pagination_token
                pagination_token = data.get("pagination_token")
                if pagination_token is None:  # No more data to fetch
                    print("[DEBUG] No more pages to fetch")
                    break

                time.sleep(2)  # Add delay between pagination requests
                conn.close()

            return all_posts[:max_posts]  # Return only requested number of posts

        except json.JSONDecodeError as e:
            print(f"[ERROR] Failed to parse JSON response: {str(e)}")
            return []
        except Exception as e:
            print(f"[ERROR] Error fetching posts: {str(e)}")
            print(f"[ERROR] Error type: {type(e).__name__}")
            return []
        finally:
            conn.close()

    def download_media(self, url: str, cloud_path: str) -> bool:
        """Download media from URL and upload to cloud storage"""
        try:
            print(f"\n[DEBUG] Downloading media from: {url}")
            print(f"[DEBUG] Saving to cloud path: {cloud_path}")

            response = requests.get(url, stream=True)
            response.raise_for_status()

            # Upload directly to cloud storage
            file_data = response.content
            cloud_url = self.cloud_storage.upload_file(file_data, cloud_path)
            print(f"[DEBUG] Uploaded to cloud storage: {cloud_url}")
            return True

        except Exception as e:
            print(f"[ERROR] Error processing media from {url}: {str(e)}")
            print(f"[ERROR] Error type: {type(e).__name__}")
            return False

    def extract_post_metadata(
        self,
        posts: List[Dict],
        username: str,
        existing_metadata: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Extract metadata from posts and return as DataFrame"""
        metadata = []
        for post in posts:
            # Extract basic post information
            post_id = post.get("code", "")  # Instagram post code
            caption_data = post.get("caption", {})
            caption_text = (
                caption_data.get("text", "")
                if isinstance(caption_data, dict)
                else str(caption_data)
            )
            timestamp = post.get("taken_at_timestamp", "")

            # Determine media type and extract media URLs
            media_type = post.get("media_type", "")
            if not media_type:
                if post.get("is_video", False):
                    media_type = "video"
                elif post.get("carousel_media"):
                    media_type = "album"
                else:
                    media_type = "image"

            # Extract media URLs based on type
            media_urls = []
            if media_type == "album" and post.get("carousel_media"):
                for item in post["carousel_media"]:
                    if item.get("video_versions"):
                        url = item["video_versions"][0].get("url", "")
                    else:
                        url = (
                            item.get("image_versions2", {})
                            .get("candidates", [{}])[0]
                            .get("url", "")
                        )
                    if url:
                        media_urls.append(url)
            elif media_type == "video" or post.get("is_video", False):
                if post.get("video_versions"):
                    url = post["video_versions"][0].get("url", "")
                    if url:
                        media_urls.append(url)
            else:  # Single image
                url = (
                    post.get("image_versions2", {})
                    .get("candidates", [{}])[0]
                    .get("url", "")
                )
                if url:
                    media_urls.append(url)

            # If no URLs found, try alternate fields
            if not media_urls:
                if post.get("video_url"):
                    media_urls.append(post["video_url"])
                elif post.get("thumbnail_url"):
                    media_urls.append(post["thumbnail_url"])
                elif post.get("display_url"):
                    media_urls.append(post["display_url"])

            print(f"[DEBUG] Found {len(media_urls)} media URLs for post {post_id}")

            # Generate GCS location
            base_cloud_path = f"instagram/{username}/media"
            if media_type == "album":
                gcs_location = f"{base_cloud_path}/post_{post_id}_album"
            else:
                ext = media_urls[0].split("?")[0].split(".")[-1] if media_urls else ""
                gcs_location = (
                    f"{base_cloud_path}/post_{post_id}_{media_type}.{ext}"
                    if ext
                    else ""
                )

            post_data = {
                "username": username,
                "post_id": post_id,
                "caption": caption_text,
                "timestamp": timestamp,
                "media_type": media_type,
                "like_count": post.get("like_count", 0),
                "comment_count": post.get("comment_count", 0),
                "media_urls": media_urls,
                "processed": False,
                "vertex_ai_labels": [],
                "vertex_ai_objects": [],
                "vertex_ai_text": "",
                "error": "",
                "gcs_location": gcs_location,
                "ai_content_description": "",
                "ai_processed_time": None,
            }
            metadata.append(post_data)

        new_metadata_df = pd.DataFrame(metadata)

        # Convert any remaining NumPy arrays to Python lists
        for column in new_metadata_df.columns:
            if len(new_metadata_df) > 0 and isinstance(
                new_metadata_df[column].iloc[0], np.ndarray
            ):
                new_metadata_df[column] = new_metadata_df[column].apply(
                    lambda x: x.tolist() if isinstance(x, np.ndarray) else x
                )

        if existing_metadata is not None:
            # Only add new posts that aren't in existing metadata
            existing_post_ids = set(existing_metadata["post_id"])
            new_metadata_df = new_metadata_df[
                ~new_metadata_df["post_id"].isin(existing_post_ids)
            ]

            if not new_metadata_df.empty:
                new_metadata_df = pd.concat(
                    [existing_metadata, new_metadata_df], ignore_index=True
                )
            else:
                new_metadata_df = existing_metadata

        return new_metadata_df

    def process_media_content(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process media content using Vertex AI and update metadata"""
        processed_count = 0
        skipped_count = 0

        for idx, row in df.iterrows():
            try:
                # Only process if not already processed or if ai_content_description is empty
                if (
                    pd.isna(row["ai_processed_time"])
                    or not row["ai_content_description"]
                ):
                    if not row["gcs_location"]:
                        print(
                            f"[WARNING] Skipping post {row['post_id']}: No media file in cloud storage"
                        )
                        skipped_count += 1
                        continue

                    gcs_uri = f"gs://{self.bucket_name}/{row['gcs_location']}"
                    print(
                        f"\n[INFO] Processing {row['media_type']} content for post {row['post_id']}"
                    )

                    # Determine media type and process accordingly
                    if row["media_type"] in ["post", "image"]:
                        analysis_results = self.media_processor.process_image(gcs_uri)
                        # Ensure consistent structure
                        analysis_results = {
                            "description": analysis_results.get("description", ""),
                            "style": analysis_results.get("style", ""),
                            "text": analysis_results.get("text", ""),
                            "safety": analysis_results.get("safety", ""),
                            "dialogue": "",
                            "scenes": "",
                            "album_images": [],
                        }
                        content_description = (
                            self.media_processor.generate_content_description(
                                analysis_results, "image"
                            )
                        )
                    elif row["media_type"] in ["reel", "video"]:
                        analysis_results = self.media_processor.process_video(gcs_uri)
                        # Ensure consistent structure
                        analysis_results = {
                            "description": analysis_results.get("description", ""),
                            "style": "",
                            "text": "",
                            "safety": analysis_results.get("safety", ""),
                            "dialogue": analysis_results.get("dialogue", ""),
                            "scenes": analysis_results.get("scenes", ""),
                            "album_images": [],
                        }
                        content_description = (
                            self.media_processor.generate_content_description(
                                analysis_results, "video"
                            )
                        )
                    elif row["media_type"] == "album":
                        # Create grid images first
                        grid_base_path = f"{row['gcs_location']}/grids"
                        grid_paths = self.image_processor.process_album_images(
                            row["gcs_location"], len(row["media_urls"]), grid_base_path
                        )

                        # Get album context from post title
                        album_context = row["caption"]

                        # Process all grid images together
                        grid_uris = [
                            f"gs://{self.bucket_name}/{path}" for path in grid_paths
                        ]

                        # Process first image with additional images
                        grid_results = self.media_processor.process_image(
                            grid_uris[0],
                            is_album=True,
                            album_context=album_context,
                            additional_images=grid_uris[1:]
                            if len(grid_uris) > 1
                            else None,
                        )

                        # Create final analysis results
                        analysis_results = {
                            "description": grid_results.get("description", ""),
                            "style": grid_results.get("style", ""),
                            "text": grid_results.get("text", ""),
                            "safety": grid_results.get("safety", ""),
                            "dialogue": "",
                            "scenes": "",
                            "album_images": [grid_results],  # Keep for compatibility
                        }
                        content_description = grid_results.get("description", "")
                    else:
                        print(
                            f"[WARNING] Skipping unknown media type: {row['media_type']}"
                        )
                        skipped_count += 1
                        continue

                    # Update DataFrame with AI analysis results and timestamp
                    df.at[idx, "ai_analysis_results"] = analysis_results
                    df.at[idx, "ai_content_description"] = content_description
                    df.at[idx, "ai_processed_time"] = datetime.now().timestamp()
                    processed_count += 1

                    print(f"[INFO] Content Description: {content_description[:200]}...")
                    time.sleep(1)  # Rate limiting
                else:
                    skipped_count += 1

            except Exception as e:
                print(
                    f"[ERROR] Failed to process media for post {row['post_id']}: {str(e)}"
                )
                skipped_count += 1
                continue

        print(
            f"\n[SUMMARY] Processed {processed_count} items, Skipped {skipped_count} items"
        )
        return df

    def display_metadata_table(self, df: pd.DataFrame) -> None:
        """Display metadata table in a readable format"""
        display_df = df.copy()

        # Safely truncate string fields and handle non-string values
        def safe_truncate(value, max_length=50):
            if pd.isna(value):
                return ""
            str_value = str(value)
            return (
                str_value[:max_length] + "..."
                if len(str_value) > max_length
                else str_value
            )

        # Truncate long fields for display with safe handling
        display_df["caption"] = display_df["caption"].apply(safe_truncate)
        display_df["media_urls"] = display_df["media_urls"].apply(
            lambda x: f"{len(x)} media items" if isinstance(x, list) else "1 media item"
        )
        display_df["gcs_location"] = display_df["gcs_location"].apply(
            lambda x: safe_truncate(x) if x else ""
        )
        display_df["ai_content_description"] = display_df[
            "ai_content_description"
        ].apply(lambda x: safe_truncate(x, 100) if x else "")

        # Reorder columns to show post_id and post_link at the beginning
        columns_order = [
            "post_id",
            "caption",
            "timestamp",
            "media_type",
            "like_count",
            "comment_count",
            "media_urls",
            "processed",
            "vertex_ai_labels",
            "vertex_ai_objects",
            "vertex_ai_text",
            "error",
            "ai_content_description",
            "ai_processed_time",
            "gcs_location",
        ]
        display_df = display_df[columns_order]

        print("\nPost Metadata:")
        print(tabulate(display_df, headers="keys", tablefmt="grid", showindex=False))

    def download_media_from_metadata(self, df: pd.DataFrame, username: str) -> None:
        """Download media using metadata DataFrame and store in cloud"""
        base_cloud_path = f"instagram/{username}/media"

        for _, row in df.iterrows():
            try:
                post_id = row["post_id"]
                media_type = row["media_type"]
                media_urls = row["media_urls"]

                if not media_urls:
                    print(
                        f"[WARNING] No media URLs found for post {post_id}, skipping..."
                    )
                    continue

                if media_type == "album":
                    for idx, url in enumerate(media_urls):
                        if not url:
                            print(
                                f"[WARNING] Empty URL in album for post {post_id} at index {idx}"
                            )
                            continue
                        ext = url.split("?")[0].split(".")[-1]
                        cloud_path = (
                            f"{base_cloud_path}/post_{post_id}_album/image_{idx}.{ext}"
                        )
                        # Check if file already exists
                        if self.cloud_storage.blob_exists(cloud_path):
                            print(
                                f"[DEBUG] Media already exists at {cloud_path}, skipping..."
                            )
                            continue
                        self.download_media(url, cloud_path)
                else:
                    if not media_urls[0]:
                        print(f"[WARNING] Empty URL for post {post_id}")
                        continue
                    url = media_urls[0]
                    ext = url.split("?")[0].split(".")[-1]
                    cloud_path = f"{base_cloud_path}/post_{post_id}_{media_type}.{ext}"
                    # Check if file already exists
                    if self.cloud_storage.blob_exists(cloud_path):
                        print(
                            f"[DEBUG] Media already exists at {cloud_path}, skipping..."
                        )
                        continue
                    self.download_media(url, cloud_path)

                time.sleep(1)  # Rate limiting

            except IndexError as e:
                print(f"[ERROR] No valid media URLs for post {post_id}: {str(e)}")
                continue
            except Exception as e:
                print(f"[ERROR] Failed to download post {post_id}: {str(e)}")
                continue

    def process_profile(
        self, username: str, max_posts: int = 50
    ) -> Optional[pd.DataFrame]:
        """Process posts for a given profile and store data in cloud"""
        try:
            # Check for existing metadata
            metadata_path = f"instagram/{username}/metadata.parquet"
            existing_metadata = self.cloud_storage.download_dataframe(metadata_path)

            if existing_metadata is not None:
                print(
                    f"Found existing metadata for {username} with {len(existing_metadata)} posts"
                )

            # Fetch posts with pagination
            posts = self.get_user_posts(username, max_posts)

            if not posts:
                print(f"No posts found for {username}")
                return None

            # Create/update metadata DataFrame
            metadata_df = self.extract_post_metadata(posts, username, existing_metadata)

            if metadata_df.empty:
                print("No new posts to add to metadata")
                return existing_metadata

            # Display initial metadata table
            print("\nInitial metadata (before AI processing):")
            self.display_metadata_table(metadata_df)

            # Save initial metadata
            self.cloud_storage.upload_dataframe(metadata_df, metadata_path)
            print(f"\nInitial metadata saved to cloud storage: {metadata_path}")

            # Download media files
            print("\nDownloading media files to cloud storage...")
            self.download_media_from_metadata(metadata_df, username)
            print("Media download completed")

            # Process with Vertex AI based on initialization parameter
            if self.auto_process_with_vertex:
                print("\nProcessing media content with Vertex AI...")
                metadata_df = self.process_media_content(metadata_df)

                # Display updated metadata table
                print("\nUpdated metadata (after AI processing):")
                self.display_metadata_table(metadata_df)

                # Save updated metadata
                self.cloud_storage.upload_dataframe(metadata_df, metadata_path)
                print(f"\nUpdated metadata saved to cloud storage: {metadata_path}")

            return metadata_df

        except Exception as e:
            print(f"Error: {str(e)}")
            return None

    def run_ai_processing(self, username: str) -> Optional[pd.DataFrame]:
        """Run AI processing pipeline independently on existing metadata

        This method allows running the AI processing pipeline separately from the scraping pipeline.
        It provides three options:
        1. Update all - Process all items regardless of previous processing
        2. Update remaining - Process only items that haven't been processed yet
        3. Don't update - Skip processing
        """
        try:
            # Load existing metadata
            metadata_path = f"instagram/{username}/metadata.parquet"
            metadata_df = self.cloud_storage.download_dataframe(metadata_path)

            if metadata_df is None or metadata_df.empty:
                print(f"[ERROR] No metadata found for user {username}")
                return None

            # Count items needing processing
            unprocessed_items = metadata_df[
                metadata_df["ai_content_description"].isna()
                | (metadata_df["ai_content_description"] == "")
            ]
            total_items = len(metadata_df)
            items_to_process = len(unprocessed_items)

            print(f"\nFound {total_items} total items in metadata")
            print(f"Items not yet processed: {items_to_process}")

            # Ask for processing option
            while True:
                print("\nChoose processing option:")
                print("1. Update all - Process all items")
                print("2. Update remaining - Process only unprocessed items")
                print("3. Don't update - Skip processing")
                choice = input("Enter choice (1/2/3): ").strip()

                if choice in ["1", "2", "3"]:
                    break
                print("Invalid choice. Please enter 1, 2, or 3.")

            if choice == "3":
                print("Skipping AI processing.")
                return metadata_df

            if choice == "1":
                # Reset AI processing flags to process all items
                metadata_df["ai_content_description"] = ""
                metadata_df["ai_processed_time"] = None
                print(f"\nProcessing all {total_items} items...")
            else:  # choice == "2"
                if items_to_process == 0:
                    print("No items need processing.")
                    return metadata_df
                print(f"\nProcessing {items_to_process} remaining items...")

            # Process the items
            metadata_df = self.process_media_content(metadata_df)

            # Display updated metadata table
            print("\nUpdated metadata (after AI processing):")
            self.display_metadata_table(metadata_df)

            # Save updated metadata
            self.cloud_storage.upload_dataframe(metadata_df, metadata_path)
            print(f"\nUpdated metadata saved to cloud storage: {metadata_path}")

            return metadata_df

        except Exception as e:
            print(f"[ERROR] Failed to run AI processing: {str(e)}")
            return None
