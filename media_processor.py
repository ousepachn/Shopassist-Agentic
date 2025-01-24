from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel, Part
from typing import Dict, List, Optional
import json


class MediaProcessor:
    def __init__(self, project_id: str, location: str = "us-central1"):
        """Initialize the Media Processor with Google Cloud project details"""
        self.project_id = project_id
        self.location = location
        # Initialize Vertex AI
        aiplatform.init(project=project_id, location=location)
        # Initialize Gemini model
        self.model = GenerativeModel("gemini-1.5-flash-002")

    def process_image(self, gcs_uri: str) -> Dict:
        """Process an image using Vertex AI Gemini API

        Args:
            gcs_uri: GCS URI of the image (gs://bucket-name/path/to/image)

        Returns:
            Dict containing analysis results
        """
        try:
            # Create image part from URI
            image = Part.from_uri(gcs_uri, mime_type="image/jpeg")

            # Create prompts for different aspects of analysis
            prompts = [
                "Describe this image in detail. Include any objects, people, text, or notable elements you can see.",
                "What is the overall mood or style of this image?",
                "Is there any text visible in this image? If so, what does it say?",
                "Are there any concerning or sensitive elements in this image that should be noted?",
            ]

            results = {}
            for prompt in prompts:
                response = self.model.generate_content([image, prompt])
                key = prompt.split()[
                    1
                ].lower()  # Use first word after "what/describe/is" as key
                results[key] = response.text

            # Structure the results
            analysis_results = {
                "description": results.get("this", ""),
                "style": results.get("is", ""),
                "text": results.get("there", ""),
                "safety": results.get("are", ""),
            }

            return analysis_results

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
            # For now, we'll return a placeholder since video processing requires additional setup
            analysis_results = {
                "description": "This is a video post. Video content analysis is not supported yet.",
                "dialogue": "",
                "scenes": "",
                "safety": "",
            }

            return analysis_results

        except Exception as e:
            print(f"[ERROR] Failed to process video {gcs_uri}: {str(e)}")
            return {}

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
