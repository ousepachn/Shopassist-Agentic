import os
import logging
from typing import List, Dict, Any
from pinecone import Pinecone
from google import genai
from google.genai.types import EmbedContentConfig
from dotenv import load_dotenv
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self):
        # Get the project root directory
        project_root = Path(__file__).parent.parent.parent

        # Load environment variables from .env.local
        env_path = project_root / ".env.local"
        if env_path.exists():
            logger.info(f"Loading environment variables from {env_path}")
            load_dotenv(env_path)
        else:
            logger.warning(
                f".env.local file not found at {env_path}, using default environment variables"
            )
            load_dotenv()

        # Initialize Pinecone
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        if not pinecone_api_key:
            logger.error("PINECONE_API_KEY not found in environment variables")
            raise ValueError("PINECONE_API_KEY not found in environment variables")

        pc = Pinecone(api_key=pinecone_api_key)
        self.index_name = os.getenv("PINECONE_INDEX_NAME", "shopassist-v2")
        self.index = pc.Index(self.index_name)

        # Initialize Google AI client
        os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv("FIREBASE_PROJECT_ID")
        os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv(
            "GOOGLE_CLOUD_LOCATION", "us-central1"
        )
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

        # Set up Google Cloud credentials
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not credentials_path:
            logger.error(
                "GOOGLE_APPLICATION_CREDENTIALS not found in environment variables"
            )
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS not found in environment variables"
            )

        # Convert relative path to absolute path if necessary
        if not os.path.isabs(credentials_path):
            credentials_path = str(project_root / credentials_path)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        # Verify that the credentials file exists
        if not os.path.exists(credentials_path):
            logger.error(f"Credentials file not found at {credentials_path}")
            raise FileNotFoundError(f"Credentials file not found at {credentials_path}")

        logger.info(f"Using Google Cloud credentials from: {credentials_path}")
        self.genai_client = genai.Client()

    def create_embedding(self, text: str) -> List[float]:
        """Create embedding using Google's text-embedding-005 model."""
        try:
            logger.info(f"Creating embedding for text: {text[:100]}...")
            response = self.genai_client.models.embed_content(
                model="text-embedding-005",
                contents=[text],
                config=EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=768,
                ),
            )
            return response.embeddings[0].values
        except Exception as e:
            logger.error(f"Error creating embedding: {str(e)}")
            raise

    def search_posts(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search for posts using semantic similarity.

        Args:
            query: The search query text
            top_k: Number of results to return (default: 5)

        Returns:
            List of dictionaries containing the search results with metadata
        """
        try:
            # Create embedding for the query
            query_embedding = self.create_embedding(query)

            # Search in Pinecone
            search_results = self.index.query(
                vector=query_embedding, top_k=top_k, include_metadata=True
            )

            # Process and return results
            results = []
            for match in search_results.matches:
                result = {
                    "score": match.score,
                    "username": match.metadata.get("username", ""),
                    "content": match.metadata.get("content", ""),
                    "caption": match.metadata.get("caption", ""),
                    "timestamp": match.metadata.get("timestamp", ""),
                    "post_url": match.metadata.get("post_url", ""),
                    "gcs_metadata_url": match.metadata.get("gcs_metadata_url", ""),
                }
                results.append(result)

            logger.info(f"Found {len(results)} results for query: {query}")
            return results

        except Exception as e:
            logger.error(f"Error searching posts: {str(e)}")
            raise


# Example usage:
if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    # Get the project root directory
    project_root = Path(__file__).parent.parent.parent

    # Load environment variables from .env.local
    env_path = project_root / ".env.local"
    if not env_path.exists():
        print(f"Error: .env.local file not found at {env_path}")
        sys.exit(1)

    load_dotenv(env_path)

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Search posts using semantic similarity"
    )
    parser.add_argument("query", help="The search query text")
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of results to return (default: 5)"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    # Configure logging based on verbose flag
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Initialize search service
        print(f"Initializing search service...")
        search_service = SearchService()

        # Perform search
        print(f"Searching for: '{args.query}'")
        results = search_service.search_posts(args.query, top_k=args.top_k)

        # Display results
        print(f"\nFound {len(results)} results:")
        for i, result in enumerate(results, 1):
            print(f"\n--- Result {i} (Score: {result['score']:.4f}) ---")
            print(f"Username: {result['username']}")
            print(f"Content: {result['content']}")
            print(f"Caption: {result['caption']}")
            print(f"Timestamp: {result['timestamp']}")
            print(f"Post URL: {result['post_url']}")
            print(f"GCS Metadata URL: {result['gcs_metadata_url']}")

    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
