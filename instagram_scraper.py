import http.client
import json
import os
import requests
from typing import Dict, List, Optional
import time
from datetime import datetime


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

    def process_profile(
        self, username: str, output_dir: str = "downloads", max_posts: int = 50
    ) -> None:
        """Process posts for a given profile with pagination support"""
        try:
            # Create output directory structure
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            profile_dir = os.path.join(output_dir, f"{username}_{timestamp}")
            os.makedirs(profile_dir, exist_ok=True)

            # Fetch posts with pagination
            posts = self.get_user_posts(username, max_posts)

            if not posts:
                print(f"No posts found for {username}")
                return

            # Process each post
            for idx, post in enumerate(posts):
                try:
                    if "media_name" in post:
                        print(f"Media {idx}: {post['media_name']}")

                    # Handle carousel/album posts
                    if post["media_name"] == "album" and "carousel_media" in post:
                        # Create album directory
                        album_dir = os.path.join(profile_dir, f"post_{idx}_album")
                        os.makedirs(album_dir, exist_ok=True)

                        # Process each image in the carousel
                        for carousel_idx, carousel_item in enumerate(
                            post["carousel_media"]
                        ):
                            if "thumbnail_url" in carousel_item:
                                url = carousel_item["thumbnail_url"]
                                ext = url.split("?")[0].split(".")[-1]
                                filename = f"image_{carousel_idx}.{ext}"
                                filepath = os.path.join(album_dir, filename)
                                self.download_media(url, filepath)

                    # Handle single image posts
                    elif post["media_name"] == "post" and "thumbnail_url" in post:
                        url = post["thumbnail_url"]
                        ext = url.split("?")[0].split(".")[-1]
                        filename = f"post_{idx}_image.{ext}"
                        filepath = os.path.join(profile_dir, filename)
                        self.download_media(url, filepath)

                    # Handle video posts
                    elif "video_url" in post:
                        url = post["video_url"]
                        ext = url.split("?")[0].split(".")[-1]
                        filename = f"post_{idx}_video.{ext}"
                        filepath = os.path.join(profile_dir, filename)
                        self.download_media(url, filepath)

                    time.sleep(1)

                except Exception as e:
                    print(f"Error processing post {idx}: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error: {str(e)}")
