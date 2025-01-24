import http.client
import json
import os
import requests
from typing import Dict, List, Optional
import time
from datetime import datetime
import pandas as pd
from tabulate import tabulate


class InstagramScraper:
    def __init__(self, api_key: str):
        """Initialize the scraper with RapidAPI key"""
        self.api_key = api_key
        self.base_url = "instagram-scraper-api2.p.rapidapi.com"
        self.headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": self.base_url}

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

                conn = http.client.HTTPSConnection(self.base_url)
                conn.request("GET", url, headers=self.headers)

                response = conn.getresponse()
                data = json.loads(response.read().decode("utf-8"))

                if not data or "data" not in data or "items" not in data["data"]:
                    break

                # Add posts from current page
                posts = data["data"]["items"]
                all_posts.extend(posts)

                # Check for next page using pagination_token
                pagination_token = data.get("pagination_token")
                if pagination_token is None:  # No more data to fetch
                    break

                time.sleep(2)  # Add delay between pagination requests
                conn.close()

            return all_posts[:max_posts]  # Return only requested number of posts

        except Exception as e:
            print(f"Error fetching posts: {str(e)}")
            return []
        finally:
            conn.close()

    def download_media(self, url: str, filepath: str) -> bool:
        """Download media from URL to specified filepath"""
        try:
            print(f"\n[DEBUG] Downloading media from: {url}")
            print(f"[DEBUG] Saving to: {filepath}")

            response = requests.get(url, stream=True)
            response.raise_for_status()

            file_size = int(response.headers.get("content-length", 0))
            print(f"[DEBUG] File size: {file_size} bytes")

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            if os.path.exists(filepath):
                actual_size = os.path.getsize(filepath)
                print(f"[DEBUG] Downloaded file size: {actual_size} bytes")
                return True
            return False

        except Exception as e:
            print(f"[ERROR] Error downloading media from {url}: {str(e)}")
            print(f"[ERROR] Error type: {type(e).__name__}")
            return False

    def extract_post_metadata(self, posts: List[Dict]) -> pd.DataFrame:
        """Extract metadata from posts and create a DataFrame"""
        metadata_list = []

        for idx, post in enumerate(posts):
            media_links = []

            # Extract media links based on post type
            if post.get("media_name") == "album" and "carousel_media" in post:
                media_links = [
                    item.get("thumbnail_url")
                    for item in post["carousel_media"]
                    if "thumbnail_url" in item
                ]
            elif post.get("media_name") == "post" and "thumbnail_url" in post:
                media_links = [post["thumbnail_url"]]
            elif "video_url" in post:
                media_links = [post["video_url"]]

            # Extract caption data
            caption = post.get("caption", {})

            # Get post code and create Instagram link
            post_code = post.get("code", "")
            post_link = f"www.instagram.com/p/{post_code}" if post_code else ""

            metadata = {
                "post_id": post_code,  # Using Instagram's code as post_id
                "display_id": idx,  # Keeping the numerical index for display
                "post_title": caption.get("text", ""),
                "created_timestamp": caption.get("created_at_utc", ""),
                "post_tags": ", ".join(caption.get("hashtags", [])),
                "mentions": ", ".join(caption.get("mentions", [])),
                "post_location": post.get("location", {}).get("name", ""),
                "media_type": post.get("media_name", ""),
                "media_links": media_links,
                "post_link": post_link,
            }
            metadata_list.append(metadata)

        return pd.DataFrame(metadata_list)

    def display_metadata_table(self, df: pd.DataFrame) -> None:
        """Display metadata table in a readable format"""
        display_df = df.copy()
        # Truncate long fields for display
        display_df["post_title"] = display_df["post_title"].str[:50] + "..."
        display_df["media_links"] = display_df["media_links"].apply(
            lambda x: f"{len(x)} media items" if isinstance(x, list) else "1 media item"
        )

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
        ]
        display_df = display_df[columns_order]

        print("\nPost Metadata:")
        print(tabulate(display_df, headers="keys", tablefmt="grid", showindex=False))

    def download_media_from_metadata(self, df: pd.DataFrame, output_dir: str) -> None:
        """Download media using metadata DataFrame"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        profile_dir = os.path.join(output_dir, f"downloads_{timestamp}")
        os.makedirs(profile_dir, exist_ok=True)

        for _, row in df.iterrows():
            try:
                post_id = row["post_id"]
                media_type = row["media_type"]
                media_links = row["media_links"]

                if media_type == "album":
                    album_dir = os.path.join(profile_dir, f"post_{post_id}_album")
                    os.makedirs(album_dir, exist_ok=True)
                    for idx, url in enumerate(media_links):
                        ext = url.split("?")[0].split(".")[-1]
                        filename = f"image_{idx}.{ext}"
                        filepath = os.path.join(album_dir, filename)
                        self.download_media(url, filepath)
                else:
                    url = media_links[0]
                    ext = url.split("?")[0].split(".")[-1]
                    filename = f"post_{post_id}_{media_type}.{ext}"
                    filepath = os.path.join(profile_dir, filename)
                    self.download_media(url, filepath)

                time.sleep(1)

            except Exception as e:
                print(f"Error downloading post {post_id}: {str(e)}")
                continue

    def process_profile(
        self, username: str, output_dir: str = "downloads", max_posts: int = 50
    ) -> Optional[pd.DataFrame]:
        """Process posts for a given profile and return metadata DataFrame"""
        try:
            # Fetch posts with pagination
            posts = self.get_user_posts(username, max_posts)

            if not posts:
                print(f"No posts found for {username}")
                return None

            # Create metadata DataFrame
            metadata_df = self.extract_post_metadata(posts)

            # Display metadata table
            self.display_metadata_table(metadata_df)

            return metadata_df

        except Exception as e:
            print(f"Error: {str(e)}")
            return None
