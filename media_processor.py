from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel, Part
from typing import Dict, List, Optional
import json
import subprocess
import tempfile
import os
from google.cloud import storage


class VideoProcessor:
    def __init__(self, bucket_name: str):
        """Initialize with GCS bucket name"""
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)

    def download_video_from_gcs(self, gcs_path: str, local_path: str):
        """Download a video from GCS"""
        blob = self.bucket.blob(gcs_path)
        blob.download_to_filename(local_path)

    def upload_video_to_gcs(self, local_path: str, gcs_path: str):
        """Upload a video to GCS"""
        blob = self.bucket.blob(gcs_path)
        blob.upload_from_filename(local_path)

    def preprocess_video(self, input_path: str, output_path: str, duration: int = 15):
        """Preprocess video: trim to duration and resize to 480p with H.264 codec"""
        try:
            # FFmpeg command to trim and resize video
            command = [
                "ffmpeg",
                "-i",
                input_path,
                "-t",
                str(duration),
                "-vf",
                "scale=-1:480",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-y",
                output_path,
            ]

            # Run FFmpeg command
            result = subprocess.run(command, capture_output=True, text=True)

            if result.returncode != 0:
                print(f"[ERROR] FFmpeg error: {result.stderr}")
                return False

            return True

        except Exception as e:
            print(f"[ERROR] FFmpeg error: {str(e)}")
            return False


class MediaProcessor:
    def __init__(
        self, project_id: str, bucket_name: str, location: str = "us-central1"
    ):
        """Initialize the Media Processor with Google Cloud project details"""
        self.project_id = project_id
        self.location = location
        self.bucket_name = bucket_name
        # Initialize Vertex AI
        aiplatform.init(project=project_id, location=location)
        # Initialize Gemini model
        self.model = GenerativeModel("gemini-1.5-flash-002")
        # Initialize video processor
        self.video_processor = VideoProcessor(bucket_name)

    def process_image(
        self,
        gcs_uri: str,
        is_album: bool = False,
        album_context: str = "",
        additional_images: List[str] = None,
    ) -> Dict:
        """Process an image using Vertex AI Gemini API

        Args:
            gcs_uri: GCS URI of the image (gs://bucket-name/path/to/image)
            is_album: Whether this image is part of an album
            album_context: Context about the album (e.g. post caption) to help with analysis
            additional_images: List of additional image URIs for album processing

        Returns:
            Dict containing analysis results
        """
        try:
            # Create image parts
            images = [Part.from_uri(gcs_uri, mime_type="image/jpeg")]
            if additional_images:
                for img_uri in additional_images:
                    images.append(Part.from_uri(img_uri, mime_type="image/jpeg"))

            # Create prompts for different aspects of analysis
            if is_album:
                prompt = f"""You are an Instagram post reviewer assistant. The below series of images are from a carousel of pictures that are part of a post. Some of the pictures are arranged in a grid to offer more context. Please review and write a short description of what is happening in the album.

Please also use additional contextual data from the post title: {album_context}

Please make sure to extract the below pieces of information (if available):
- What is the post about: fashion, cooking, art, travel, etc
- Are there any brands mentioned
- Are there any products mentioned

Please also describe:
- Any text visible in the images
- Any concerning or sensitive elements that should be noted
"""
                response = self.model.generate_content([*images, prompt])
                results = {
                    "description": response.text,
                    "text": "",
                    "safety": "",
                    "album_context": "",
                }
            else:
                prompt = f"""You are an Instagram post reviewer assistant. The below image is from a post. Please review and write a short description of what is happening in the image.

Please also use additional contextual data from the post title: {album_context}

Please make sure to extract the below pieces of information (if available):
- What is the post about: fashion, cooking, art, travel, etc
- Are there any brands mentioned
- Are there any products mentioned

Please also describe:
- Any text visible in the images
- Any concerning or sensitive elements that should be noted
"""
                response = self.model.generate_content([images[0], prompt])
                results = {
                    "description": response.text,
                    "text": "",
                    "safety": "",
                    "album_context": "",
                }

            return results

        except Exception as e:
            print(f"[ERROR] Failed to process image {gcs_uri}: {str(e)}")
            return {}

    def process_video(self, gcs_uri: str) -> Dict:
        """Process a video by analyzing its key frames using Vertex AI Gemini API

        Args:
            gcs_uri: GCS URI of the video (gs://bucket-name/path/to/video)

        Returns:
            Dict containing analysis results
        """
        try:
            # Extract paths
            gcs_path = gcs_uri.replace(f"gs://{self.bucket_name}/", "")
            processed_gcs_path = f"{os.path.splitext(gcs_path)[0]}_processed.mp4"

            # Create temporary files
            with (
                tempfile.NamedTemporaryFile(suffix=".mp4") as input_temp,
                tempfile.NamedTemporaryFile(suffix=".mp4") as output_temp,
            ):
                # Download original video
                print("[INFO] Downloading video from GCS...")
                self.video_processor.download_video_from_gcs(gcs_path, input_temp.name)

                # Preprocess video
                print("[INFO] Preprocessing video...")
                if not self.video_processor.preprocess_video(
                    input_temp.name, output_temp.name
                ):
                    raise Exception("Video preprocessing failed")

                # Upload processed video
                print("[INFO] Uploading processed video to GCS...")
                self.video_processor.upload_video_to_gcs(
                    output_temp.name, processed_gcs_path
                )

                # Create video part for Gemini
                video = Part.from_uri(
                    f"gs://{self.bucket_name}/{processed_gcs_path}",
                    mime_type="video/mp4",
                )

                # Create prompt for video analysis
                prompt = """You are an Instagram post reviewer assistant. The below video is from a post. Please review and write a short description of what is happening in the video.

Please make sure to extract the below pieces of information (if available):
- What is the post about: fashion, cooking, art, travel, etc
- Are there any brands mentioned
- Are there any products mentioned
- What is the main activity or demonstration in the video

Please also describe:
- Any text overlays visible in the video
- Any concerning or sensitive elements that should be noted
"""
                # Estimate token usage
                token_estimate = self.model.count_tokens(prompt)
                print(f"[INFO] Estimated prompt tokens: {token_estimate}")

                # Process video with Gemini
                print("[INFO] Processing video with Gemini...")
                response = self.model.generate_content([video, prompt])

                # Structure the results
                analysis_results = {
                    "description": response.text,
                    "dialogue": "",  # Will be populated if speech is detected
                    "scenes": "",  # Will be populated with scene descriptions
                    "safety": "",  # Will be populated with any safety concerns
                    "token_usage": token_estimate,
                }

                return analysis_results

        except Exception as e:
            print(f"[ERROR] Failed to process video {gcs_uri}: {str(e)}")
            return {
                "description": "Failed to process video content.",
                "dialogue": "",
                "scenes": "",
                "safety": "",
                "token_usage": 0,
            }

    def generate_content_description(
        self, analysis_results: Dict, media_type: str
    ) -> str:
        """Generate a human-readable description from the analysis results

        Args:
            analysis_results: Dict containing analysis results
            media_type: Type of media ('image' or 'video')

        Returns:
            String containing a natural language description of the content
        """
        if not analysis_results:
            return "No analysis results available"

        if media_type == "image":
            descriptions = []

            # Add main description
            if "description" in analysis_results:
                descriptions.append(analysis_results["description"])

            # Add style information
            if "style" in analysis_results and analysis_results["style"]:
                descriptions.append(f"Style: {analysis_results['style']}")

            # Add text if found
            if "text" in analysis_results and analysis_results["text"]:
                descriptions.append(f"Text found: {analysis_results['text']}")

            # Add safety warning if needed
            if (
                "safety" in analysis_results
                and "concerning" in analysis_results["safety"].lower()
            ):
                descriptions.append("Note: This image may contain sensitive content")

            return "\n".join(descriptions)

        elif media_type == "video":
            descriptions = []

            # Add main description
            if "description" in analysis_results:
                descriptions.append(analysis_results["description"])

            # Add dialogue information
            if "dialogue" in analysis_results and analysis_results["dialogue"]:
                descriptions.append(f"Audio content: {analysis_results['dialogue']}")

            # Add scene information
            if "scenes" in analysis_results and analysis_results["scenes"]:
                descriptions.append(f"Scenes: {analysis_results['scenes']}")

            # Add safety warning if needed
            if (
                "safety" in analysis_results
                and "concerning" in analysis_results["safety"].lower()
            ):
                descriptions.append("Note: This video may contain sensitive content")

            return "\n".join(descriptions)

        return "Unsupported media type"
