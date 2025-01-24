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
        self, api_key: str, bucket_name: str = "shopassist-agentic-media-data"
    ):
        """Initialize the scraper with RapidAPI key and GCS bucket"""
        self.api_key = api_key
        self.base_url = "instagram-scraper-api2.p.rapidapi.com"
        self.headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": self.base_url}
        self.cloud_storage = CloudStorageHandler(bucket_name)

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
        """Extract metadata from posts and create a DataFrame"""
        metadata_list = []
        now = datetime.now().timestamp()

        if not posts:
            print("[ERROR] No posts provided to extract metadata from")
            return pd.DataFrame()

        # Create set of existing post IDs
        existing_post_ids = set()
        if existing_metadata is not None and not existing_metadata.empty:
            existing_post_ids = set(existing_metadata["post_id"].values)

        for idx, post in enumerate(posts):
            try:
                # Get post code early to check if we should skip
                post_code = post.get("code", "")
                if post_code in existing_post_ids:
                    print(f"[DEBUG] Skipping existing post {post_code}")
                    continue

                print(f"\n[DEBUG] Processing post {idx + 1}/{len(posts)}")

                # Extract media type and links
                media_type = post.get("media_name", "unknown")
                print(f"[DEBUG] Post type: {media_type}")
                media_links = []

                if media_type == "album" and post.get("carousel_media"):
                    media_links = [
                        item.get("thumbnail_url")
                        or item.get("image_versions", {})
                        .get("items", [{}])[0]
                        .get("url")
                        for item in post["carousel_media"]
                        if item.get("thumbnail_url")
                        or item.get("image_versions", {}).get("items")
                    ]
                    print(f"[DEBUG] Found {len(media_links)} images in album")
                elif media_type == "post" or media_type == "image":
                    media_links = [
                        post.get("thumbnail_url")
                        or post.get("image_versions", {})
                        .get("items", [{}])[0]
                        .get("url")
                    ]
                    print("[DEBUG] Found single image post")
                elif post.get("video_url"):
                    media_links = [post["video_url"]]
                    print("[DEBUG] Found video post")
                else:
                    print(
                        f"[WARNING] Unknown post type or no media found. Post keys: {post.keys()}"
                    )
                    media_links = []

                # Extract caption data safely
                caption = (
                    post.get("caption", {})
                    if isinstance(post.get("caption"), dict)
                    else {}
                )

                # Get post code and create Instagram link
                post_link = f"www.instagram.com/p/{post_code}" if post_code else ""

                # Extract location data safely
                location = post.get("location", {})
                location_name = (
                    location.get("name", "") if isinstance(location, dict) else ""
                )

                # Determine GCS location based on media type
                if media_links:
                    if media_type == "album":
                        gcs_location = (
                            f"instagram/{username}/media/post_{post_code}_album"
                        )
                    else:
                        ext = media_links[0].split("?")[0].split(".")[-1]
                        gcs_location = f"instagram/{username}/media/post_{post_code}_{media_type}.{ext}"
                else:
                    gcs_location = ""

                metadata = {
                    "post_id": post_code,  # Using Instagram's code as post_id
                    "display_id": idx,  # Keeping the numerical index for display
                    "post_title": caption.get("text", "")[:100] + "..."
                    if caption.get("text", "")
                    else "",
                    "created_timestamp": caption.get("created_at_utc", ""),
                    "post_tags": ", ".join(caption.get("hashtags", [])),
                    "mentions": ", ".join(caption.get("mentions", [])),
                    "post_location": location_name,
                    "media_type": media_type,
                    "media_links": media_links,
                    "post_link": post_link,
                    "gcs_location": gcs_location,
                    "last_scraped": now,
                }
                metadata_list.append(metadata)

            except Exception as e:
                print(f"[ERROR] Failed to process post {idx}: {str(e)}")
                print(f"[ERROR] Post data: {post}")
                continue

        # Create DataFrame from new posts
        new_metadata_df = (
            pd.DataFrame(metadata_list) if metadata_list else pd.DataFrame()
        )

        # Combine with existing metadata if available
        if existing_metadata is not None and not existing_metadata.empty:
            return pd.concat([existing_metadata, new_metadata_df], ignore_index=True)

        return new_metadata_df

    def display_metadata_table(self, df: pd.DataFrame) -> None:
        """Display metadata table in a readable format"""
        display_df = df.copy()
        # Truncate long fields for display
        display_df["post_title"] = display_df["post_title"].str[:50] + "..."
        display_df["media_links"] = display_df["media_links"].apply(
            lambda x: f"{len(x)} media items" if isinstance(x, list) else "1 media item"
        )
        display_df["gcs_location"] = display_df["gcs_location"].str[:50] + "..."

        # Reorder columns to show post_id and post_link at the beginning
        columns_order = [
            "display_id",
            "post_id",
            "post_link",
            "post_title",
            "created_timestamp",
            "post_tags",
            "mentions",
            "post_location",
            "media_type",
            "media_links",
            "gcs_location",
            "last_scraped",
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
                media_links = row["media_links"]

                if media_type == "album":
                    for idx, url in enumerate(media_links):
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
                    url = media_links[0]
                    ext = url.split("?")[0].split(".")[-1]
                    cloud_path = f"{base_cloud_path}/post_{post_id}_{media_type}.{ext}"
                    # Check if file already exists
                    if self.cloud_storage.blob_exists(cloud_path):
                        print(
                            f"[DEBUG] Media already exists at {cloud_path}, skipping..."
                        )
                        continue
                    self.download_media(url, cloud_path)

                time.sleep(1)

            except Exception as e:
                print(f"Error downloading post {post_id}: {str(e)}")
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

            # Display metadata table
            self.display_metadata_table(metadata_df)

            # Save metadata as parquet in cloud storage
            self.cloud_storage.upload_dataframe(metadata_df, metadata_path)
            print(f"\nMetadata saved to cloud storage: {metadata_path}")

            return metadata_df

        except Exception as e:
            print(f"Error: {str(e)}")
            return None
