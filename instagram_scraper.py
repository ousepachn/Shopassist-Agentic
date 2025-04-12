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
from dotenv import load_dotenv


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

    def list_blobs(self, prefix: str = "") -> List[storage.Blob]:
        """List all blobs in the bucket with the given prefix

        Args:
            prefix: The prefix to filter blobs by

        Returns:
            List of blobs matching the prefix
        """
        return list(self.bucket.list_blobs(prefix=prefix))


class InstagramScraper:
    def __init__(
        self,
        api_key: Optional[str] = None,
        bucket_name: str = "shopassist-agentic-media-data",
        project_id: str = "shopassist-agentic",
        auto_process_with_vertex: bool = False,
    ):
        """Initialize the scraper with RapidAPI key and GCS bucket"""
        load_dotenv()
        self.api_key = api_key or os.getenv("RAPIDAPI_KEY")
        if not self.api_key:
            raise ValueError(
                "API key is required. Set RAPIDAPI_KEY environment variable or pass it directly."
            )
        self.base_url = "instagram-scraper-api2.p.rapidapi.com"
        self.headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.base_url,
        }
        self.cloud_storage = CloudStorageHandler(bucket_name)
        self.media_processor = MediaProcessor(project_id, bucket_name)
        self.image_processor = ImageGridProcessor(bucket_name)
        self.bucket_name = bucket_name
        self.auto_process_with_vertex = auto_process_with_vertex
        # Media type mapping for RapidAPI
        self.media_type_map = {1: "post", 2: "reel", 8: "album"}

    def get_user_posts(self, username: str, max_posts: int = 50) -> List[Dict]:
        """Fetch posts for a given username with pagination support"""
        all_posts = []
        pagination_token = None

        try:
            while len(all_posts) < max_posts:
                # Construct URL with pagination token if available
                url = f"/v1/posts?username_or_id_or_url={username}"
                if pagination_token:
                    url += f"&pagination_token={pagination_token}"

                print(f"\n[DEBUG] Requesting URL: {url}")
                conn = http.client.HTTPSConnection(self.base_url)
                conn.request("GET", url, headers=self.headers)

                response = conn.getresponse()
                response_data = response.read().decode("utf-8")
                print(f"[DEBUG] Raw API response: {response_data}")
                print(f"[DEBUG] Response status: {response.status}")

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

            # Ensure URL is a string
            if not isinstance(url, str):
                url = str(url)

            # Check if URL is empty
            if not url or url.strip() == "":
                print(f"[ERROR] Empty URL provided for {cloud_path}")
                return False

            response = requests.get(url, stream=True)
            response.raise_for_status()

            # Upload directly to cloud storage
            file_data = response.content
            cloud_url = self.cloud_storage.upload_file(file_data, cloud_path)
            print(f"[DEBUG] Uploaded to cloud storage: {cloud_url}")
            return True

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Network error downloading media from {url}: {str(e)}")
            return False
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
            print(f"\n[DEBUG] Raw post data for {post_id}:")
            print(f"[DEBUG] taken_at field: {post.get('taken_at')}")
            print(f"[DEBUG] taken_at type: {type(post.get('taken_at'))}")
            print(f"[DEBUG] All post fields: {list(post.keys())}")
            print(f"[DEBUG] Full post data: {json.dumps(post, indent=2)}")

            # Debug caption data
            caption_data = post.get("caption", {})
            print(f"[DEBUG] Caption data type: {type(caption_data)}")
            print(f"[DEBUG] Caption data: {json.dumps(caption_data, indent=2)}")

            caption_text = (
                caption_data.get("text", "")
                if isinstance(caption_data, dict)
                else str(caption_data)
            )
            print(f"[DEBUG] Extracted caption text: {caption_text}")

            # Extract and format timestamp
            timestamp = None
            # Try different timestamp fields in order of preference
            timestamp_fields = ["taken_at_utc", "taken_at"]

            for field in timestamp_fields:
                field_value = post.get(field)
                if field_value:
                    try:
                        if isinstance(field_value, (int, str)):
                            timestamp = pd.Timestamp.fromtimestamp(int(field_value))
                            print(
                                f"[DEBUG] Successfully extracted timestamp from {field}: {timestamp}"
                            )
                            break
                    except (ValueError, TypeError) as e:
                        print(
                            f"[DEBUG] Error converting {field} value {field_value}: {e}"
                        )
                        continue

            if timestamp is None:
                print(f"[WARNING] No valid timestamp found for post {post_id}")
                # If this post exists in existing metadata, use that timestamp
                if (
                    existing_metadata is not None
                    and post_id in existing_metadata["post_id"].values
                ):
                    existing_timestamp = existing_metadata.loc[
                        existing_metadata["post_id"] == post_id, "timestamp"
                    ].iloc[0]
                    if pd.notna(existing_timestamp):
                        timestamp = pd.Timestamp(existing_timestamp)
                        print(
                            f"[DEBUG] Using existing timestamp for post {post_id}: {timestamp}"
                        )
                    else:
                        # Use current time as last resort
                        timestamp = pd.Timestamp.now()
                        print(
                            f"[DEBUG] Using current time for post {post_id}: {timestamp}"
                        )
                else:
                    # Use current time as last resort
                    timestamp = pd.Timestamp.now()
                    print(f"[DEBUG] Using current time for post {post_id}: {timestamp}")

            # Determine media type using the mapping
            raw_media_type = post.get("media_type")
            if isinstance(raw_media_type, (int, str)):
                # Convert string to int if needed
                type_key = (
                    int(raw_media_type)
                    if isinstance(raw_media_type, str)
                    else raw_media_type
                )
                media_type = self.media_type_map.get(
                    type_key, "post"
                )  # Default to "post" if unknown
            else:
                # Fallback logic for determining media type
                if post.get("is_video", False) or post.get("video_versions"):
                    media_type = "reel"
                elif post.get("carousel_media"):
                    media_type = "album"
                else:
                    media_type = "post"

            # Extract media URLs based on type
            media_urls = []
            if media_type == "album" and post.get("carousel_media"):
                for item in post["carousel_media"]:
                    try:
                        if item.get("is_video", False):
                            # Handle video in album
                            url = item.get("video_url") or item.get("thumbnail_url", "")
                        else:
                            # Handle image in album - check both new and old response structures
                            if "image_versions" in item and isinstance(
                                item["image_versions"], list
                            ):
                                # Old structure
                                url = item["image_versions"][0].get("url", "")
                            elif "image_versions" in item and isinstance(
                                item["image_versions"], dict
                            ):
                                # New structure
                                url = (
                                    item["image_versions"]
                                    .get("items", [{}])[0]
                                    .get("url", "")
                                )
                            else:
                                # Fallback to thumbnail_url
                                url = item.get("thumbnail_url", "")

                        if url:
                            media_urls.append(str(url))  # Ensure URL is string
                        else:
                            print(
                                f"[WARNING] No URL found for album item: {json.dumps(item, indent=2)}"
                            )

                    except Exception as e:
                        print(
                            f"[ERROR] Failed to extract URL from album item: {str(e)}"
                        )
                        print(f"[DEBUG] Album item data: {json.dumps(item, indent=2)}")
                        continue

            elif media_type == "reel":
                if post.get("video_versions"):
                    url = post["video_versions"][0].get("url", "")
                    if url:
                        media_urls.append(str(url))
                elif post.get("video_url"):  # Fallback
                    media_urls.append(str(post["video_url"]))
            else:  # Single post
                # Try different possible structures for single image
                if "image_versions2" in post:
                    url = (
                        post["image_versions2"]
                        .get("candidates", [{}])[0]
                        .get("url", "")
                    )
                elif "image_versions" in post and isinstance(
                    post["image_versions"], dict
                ):
                    url = post["image_versions"].get("items", [{}])[0].get("url", "")
                elif "thumbnail_url" in post:
                    url = post["thumbnail_url"]
                else:
                    url = post.get("display_url", "")

                if url:
                    media_urls.append(str(url))

            # Debug logging
            print(f"[DEBUG] Media type: {media_type}")
            print(f"[DEBUG] Found {len(media_urls)} media URLs for post {post_id}")
            for idx, url in enumerate(media_urls):
                print(
                    f"[DEBUG] Media URL {idx}: {url[:100]}..."
                )  # Print first 100 chars of URL

            # Generate GCS location
            base_cloud_path = f"instagram/{username}/media"
            if media_type == "album":
                gcs_location = f"{base_cloud_path}/post__{post_id}__album"
            else:
                ext = media_urls[0].split("?")[0].split(".")[-1] if media_urls else ""
                gcs_location = (
                    f"{base_cloud_path}/post__{post_id}__{media_type}.{ext}"
                    if ext
                    else ""
                )

            # Create metadata dictionary for this post
            post_metadata = {
                "username": username,
                "post_id": post_id,
                "caption": caption_text,
                "timestamp": timestamp,  # This is now a pd.Timestamp object
                "media_type": media_type,
                "like_count": post.get("like_count", 0),
                "comment_count": post.get("comment_count", 0),
                "media_urls": media_urls,
                "media_processed": False,
                "media_processed_urls": [],
                "media_processed_timestamp": None,
                "media_processed_error": None,
                "gcs_location": gcs_location,
                "ai_content_description": "",
                "ai_processed_time": None,
                "ai_analysis_results": {
                    "status": "pending"
                },  # Initialize with a dummy field
            }
            metadata.append(post_metadata)

        # Create DataFrame from metadata
        new_metadata_df = pd.DataFrame(metadata)

        # Ensure timestamp column is datetime64[ns]
        if "timestamp" in new_metadata_df.columns:
            # Convert any string timestamps to datetime
            new_metadata_df["timestamp"] = pd.to_datetime(
                new_metadata_df["timestamp"], errors="coerce"
            )
            # Fill any NaT values with None to ensure proper handling
            new_metadata_df["timestamp"] = new_metadata_df["timestamp"].where(
                pd.notna(new_metadata_df["timestamp"]), None
            )

        # Print all timestamps from posts
        print("\nTimestamps from posts:")
        for _, row in new_metadata_df.iterrows():
            print(f"Post {row['post_id']}: Timestamp={row['timestamp']}")

        # Convert any remaining NumPy arrays to Python lists
        for column in new_metadata_df.columns:
            if len(new_metadata_df) > 0 and isinstance(
                new_metadata_df[column].iloc[0], np.ndarray
            ):
                new_metadata_df[column] = new_metadata_df[column].apply(
                    lambda x: [str(url) for url in x.tolist()]
                    if isinstance(x, np.ndarray)
                    else x
                )

        # Ensure media_urls are always lists of strings
        new_metadata_df["media_urls"] = new_metadata_df["media_urls"].apply(
            lambda x: [str(url) for url in x]
            if isinstance(x, (list, np.ndarray))
            else [str(x)]
            if isinstance(x, str)
            else []
        )

        # Debug print media_urls types
        print("\n[DEBUG] Media URLs types after conversion:")
        for idx, row in new_metadata_df.iterrows():
            print(f"Post {row['post_id']} media_urls type: {type(row['media_urls'])}")
            print(f"Media URLs: {row['media_urls']}")

        # Additional check to ensure all media_urls are lists
        for idx, row in new_metadata_df.iterrows():
            if not isinstance(row["media_urls"], list):
                print(
                    f"[WARNING] Converting non-list media_urls for post {row['post_id']} to list"
                )
                if isinstance(row["media_urls"], str):
                    new_metadata_df.at[idx, "media_urls"] = [row["media_urls"]]
                elif isinstance(row["media_urls"], np.ndarray):
                    new_metadata_df.at[idx, "media_urls"] = row["media_urls"].tolist()
                else:
                    new_metadata_df.at[idx, "media_urls"] = []

        if existing_metadata is not None:
            # Create a lookup dictionary for new metadata
            new_metadata_lookup = {
                row["post_id"]: row for _, row in new_metadata_df.iterrows()
            }

            # Update timestamps in existing metadata
            for idx, row in existing_metadata.iterrows():
                post_id = row["post_id"]
                if post_id in new_metadata_lookup:
                    new_timestamp = new_metadata_lookup[post_id]["timestamp"]
                    if new_timestamp:  # Only update if new timestamp is not empty
                        existing_metadata.at[idx, "timestamp"] = new_timestamp
                        print(
                            f"[DEBUG] Updated timestamp for existing post {post_id}: {new_timestamp}"
                        )

            # Only add posts that aren't in existing metadata
            existing_post_ids = set(existing_metadata["post_id"])
            new_posts_df = new_metadata_df[
                ~new_metadata_df["post_id"].isin(existing_post_ids)
            ]

            if not new_posts_df.empty:
                print(
                    f"\n[DEBUG] Adding {len(new_posts_df)} new posts to existing metadata"
                )
                new_metadata_df = pd.concat(
                    [existing_metadata, new_posts_df], ignore_index=True
                )
            else:
                print("\n[DEBUG] No new posts to add")
                new_metadata_df = existing_metadata

            # Ensure ai_analysis_results is always a dictionary
            if "ai_analysis_results" in new_metadata_df.columns:
                new_metadata_df["ai_analysis_results"] = new_metadata_df[
                    "ai_analysis_results"
                ].apply(
                    lambda x: {} if pd.isna(x) else (x if isinstance(x, dict) else {})
                )

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
                    if row["media_type"] == "post":
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
                    elif row["media_type"] == "reel":
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
                    df.at[idx, "ai_analysis_results"] = (
                        analysis_results  # Store as dict, not JSON string
                    )
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
        if "caption" in display_df.columns:
            display_df["caption"] = display_df["caption"].apply(safe_truncate)
        if "media_urls" in display_df.columns:
            display_df["media_urls"] = display_df["media_urls"].apply(
                lambda x: f"{len(x)} media items"
                if isinstance(x, list)
                else "1 media item"
            )
        if "gcs_location" in display_df.columns:
            display_df["gcs_location"] = display_df["gcs_location"].apply(
                lambda x: safe_truncate(x) if x else ""
            )
        if "ai_content_description" in display_df.columns:
            display_df["ai_content_description"] = display_df[
                "ai_content_description"
            ].apply(lambda x: safe_truncate(x, 100) if x else "")

        # Get available columns that match our desired order
        desired_columns = [
            "post_id",
            "caption",
            "timestamp",
            "media_type",
            "like_count",
            "comment_count",
            "media_urls",
            "processed",
            "ai_content_description",
            "ai_processed_time",
            "gcs_location",
        ]

        # Filter to only include columns that exist in the DataFrame
        columns_to_display = [
            col for col in desired_columns if col in display_df.columns
        ]
        display_df = display_df[columns_to_display]

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

                # Ensure media_urls is a list
                if isinstance(media_urls, str):
                    media_urls = [media_urls]
                elif isinstance(media_urls, np.ndarray):
                    media_urls = media_urls.tolist()
                elif not isinstance(media_urls, list):
                    print(
                        f"[WARNING] Unexpected media_urls type for post {post_id}: {type(media_urls)}"
                    )
                    media_urls = []

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
                        cloud_path = f"{base_cloud_path}/post__{post_id}__album/image_{idx}.{ext}"
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
                    cloud_path = (
                        f"{base_cloud_path}/post__{post_id}__{media_type}.{ext}"
                    )
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
                return existing_metadata

            # Create/update metadata DataFrame - pass existing_metadata to properly merge
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

            # Verify metadata integrity to ensure it accurately reflects all files
            print("\nVerifying metadata integrity...")
            metadata_df = self.verify_metadata_integrity(username)
            if metadata_df is not None:
                print(f"Final metadata contains {len(metadata_df)} records")

            return metadata_df

        except Exception as e:
            print(f"Error: {str(e)}")
            return None

    def run_ai_processing(
        self, username: str, processing_option: str = "update_remaining"
    ) -> Optional[pd.DataFrame]:
        """Run AI processing pipeline independently on existing metadata

        Args:
            username: Instagram username to process
            processing_option: One of 'update_all', 'update_remaining', or 'skip'

        Returns:
            Optional[pd.DataFrame]: Updated metadata DataFrame or None if processing fails
        """
        try:
            # Load existing metadata
            metadata_path = f"instagram/{username}/metadata.parquet"
            metadata_df = self.cloud_storage.download_dataframe(metadata_path)

            if metadata_df is None or metadata_df.empty:
                print(f"[ERROR] No metadata found for user {username}")
                return None

            # Ensure ai_analysis_results is always a dictionary
            if "ai_analysis_results" in metadata_df.columns:
                metadata_df["ai_analysis_results"] = metadata_df[
                    "ai_analysis_results"
                ].apply(
                    lambda x: {} if pd.isna(x) else (x if isinstance(x, dict) else {})
                )

            # Count items needing processing
            unprocessed_items = metadata_df[
                metadata_df["ai_content_description"].isna()
                | (metadata_df["ai_content_description"] == "")
            ]
            total_items = len(metadata_df)
            items_to_process = len(unprocessed_items)

            print(f"\nFound {total_items} total items in metadata")
            print(f"Items not yet processed: {items_to_process}")

            # Process based on the provided option
            if processing_option == "skip":
                print("Skipping AI processing.")
                return metadata_df

            if processing_option == "update_all":
                # Reset AI processing flags to process all items
                metadata_df["ai_content_description"] = ""
                metadata_df["ai_processed_time"] = None
                metadata_df["ai_analysis_results"] = metadata_df[
                    "ai_analysis_results"
                ].apply(lambda x: {"status": "pending"})
                print(f"\nProcessing all {total_items} items...")
            else:  # update_remaining
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

            # Verify metadata integrity to ensure it accurately reflects all files
            print("\nVerifying metadata integrity...")
            metadata_df = self.verify_metadata_integrity(username)
            if metadata_df is not None:
                print(f"Final metadata contains {len(metadata_df)} records")

            return metadata_df

        except Exception as e:
            print(f"[ERROR] Failed to run AI processing: {str(e)}")
            return None

    def verify_metadata_integrity(self, username: str) -> Optional[pd.DataFrame]:
        """Verify that metadata accurately reflects all files in the media folder

        This method:
        1. Checks if all media files referenced in metadata exist in cloud storage
        2. Checks if all media files in cloud storage are referenced in metadata
        3. Updates metadata to reflect the actual state of media files

        Returns:
            Optional[pd.DataFrame]: Updated metadata DataFrame or None if verification fails
        """
        try:
            # Load existing metadata
            metadata_path = f"instagram/{username}/metadata.parquet"
            metadata_df = self.cloud_storage.download_dataframe(metadata_path)

            if metadata_df is None or metadata_df.empty:
                print(f"[ERROR] No metadata found for user {username}")
                return None

            print(f"\nVerifying metadata integrity for {username}")
            print(f"Found {len(metadata_df)} records in metadata")

            # Base path for media files
            base_cloud_path = f"instagram/{username}/media"

            # Check if all media files referenced in metadata exist in cloud storage
            missing_files = []
            for idx, row in metadata_df.iterrows():
                post_id = row["post_id"]
                media_type = row["media_type"]
                gcs_location = row["gcs_location"]

                if not gcs_location:
                    print(f"[WARNING] Post {post_id} has no GCS location")
                    missing_files.append((post_id, gcs_location))
                    continue

                if media_type == "album":
                    # For albums, check if at least one file exists in the album directory
                    album_prefix = f"{gcs_location}/"
                    album_files = self.cloud_storage.list_blobs(prefix=album_prefix)

                    if not album_files:
                        missing_files.append((post_id, gcs_location))
                        print(
                            f"[WARNING] Album directory empty or missing for post {post_id}: {gcs_location}"
                        )
                    else:
                        print(
                            f"[INFO] Found {len(album_files)} files in album for post {post_id}"
                        )
                else:
                    # For single media files, check if the file exists
                    if not self.cloud_storage.blob_exists(gcs_location):
                        missing_files.append((post_id, gcs_location))
                        print(
                            f"[WARNING] Media file missing for post {post_id}: {gcs_location}"
                        )

            # If there are missing files, remove those records from metadata
            if missing_files:
                print(f"\nFound {len(missing_files)} missing media files")
                missing_post_ids = [post_id for post_id, _ in missing_files]

                # Remove records with missing media files
                original_count = len(metadata_df)
                metadata_df = metadata_df[
                    ~metadata_df["post_id"].isin(missing_post_ids)
                ]
                removed_count = original_count - len(metadata_df)

                print(f"Removed {removed_count} records with missing media files")

            # List all media files in the cloud storage
            all_media_files = []
            prefix = f"{base_cloud_path}/"

            # List all blobs with the prefix
            blobs = self.cloud_storage.list_blobs(prefix=prefix)
            for blob in blobs:
                all_media_files.append(blob.name)

            print(f"\nFound {len(all_media_files)} media files in cloud storage")

            # Check if all media files in cloud storage are referenced in metadata
            unreferenced_files = []
            for file_path in all_media_files:
                # Extract post_id from file path
                # Format: instagram/{username}/media/post__{post_id}__{media_type}.{ext}
                # or: instagram/{username}/media/post__{post_id}__album/image_{idx}.{ext}
                parts = file_path.split("/")
                if len(parts) < 4:
                    continue

                filename = parts[-1]
                if filename.startswith("post__"):
                    post_id = filename.split("__")[1]
                    if post_id not in metadata_df["post_id"].values:
                        unreferenced_files.append(file_path)
                        print(f"[WARNING] Unreferenced media file: {file_path}")

            # If there are unreferenced files, add them to metadata
            if unreferenced_files:
                print(f"\nFound {len(unreferenced_files)} unreferenced media files")
                for file_path in unreferenced_files:
                    # Extract post_id and media_type from file path
                    parts = file_path.split("/")
                    filename = parts[-1]

                    if filename.startswith("post__"):
                        post_id = filename.split("__")[1]
                        media_type = filename.split("__")[2].split(".")[0]

                        # Create a new record for this unreferenced file
                        new_record = {
                            "username": username,
                            "post_id": post_id,
                            "caption": "",
                            "timestamp": pd.Timestamp.now(),
                            "media_type": media_type,
                            "like_count": 0,
                            "comment_count": 0,
                            "media_urls": [],
                            "media_processed": False,
                            "media_processed_urls": [],
                            "media_processed_timestamp": None,
                            "media_processed_error": None,
                            "gcs_location": file_path,
                            "ai_content_description": "",
                            "ai_processed_time": None,
                            "ai_analysis_results": {"status": "pending"},
                        }

                        # Add the new record to metadata
                        metadata_df = pd.concat(
                            [metadata_df, pd.DataFrame([new_record])], ignore_index=True
                        )
                        print(f"Added unreferenced file to metadata: {file_path}")

            # Save updated metadata
            if missing_files or unreferenced_files:
                self.cloud_storage.upload_dataframe(metadata_df, metadata_path)
                print(f"\nUpdated metadata saved to cloud storage: {metadata_path}")
            else:
                print("\nMetadata integrity verified - no issues found")

            return metadata_df

        except Exception as e:
            print(f"[ERROR] Failed to verify metadata integrity: {str(e)}")
            return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        username = sys.argv[1]
        print(f"\n[INFO] Starting scrape for user: {username}")
        try:
            # Initialize scraper
            scraper = InstagramScraper()
            # Get posts
            posts = scraper.get_user_posts(username)
            if posts:
                print(f"[INFO] Found {len(posts)} posts")
                # Process posts
                metadata_df = scraper.extract_post_metadata(posts, username)
                if metadata_df is not None:
                    print("\n[INFO] Final metadata:")
                    scraper.display_metadata_table(metadata_df)
                else:
                    print("[ERROR] Failed to create metadata DataFrame")
            else:
                print("[ERROR] No posts found")
        except Exception as e:
            print(f"[ERROR] Scraping failed: {str(e)}")
            import traceback

            traceback.print_exc()
    else:
        print("Please provide a username as argument")
