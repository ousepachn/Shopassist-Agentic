import os
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from pinecone import Pinecone
from typing import List, Dict, Any, Optional
import logging
from google import genai
from google.genai.types import EmbedContentConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PineconeSync:
    def __init__(self, username: Optional[str] = None):
        # Initialize Firebase
        if not firebase_admin._apps:
            cred = credentials.Certificate(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()
        self.username = username

        # Initialize Pinecone
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        self.index_name = os.getenv("PINECONE_INDEX_NAME", "shopassist-v2")

        # Create index if it doesn't exist
        try:
            if self.index_name not in pc.list_indexes():
                # Check Pinecone documentation for the correct parameters
                # For version 6.0.0, we need to use spec parameter
                from pinecone import ServerlessSpec

                pc.create_index(
                    name=self.index_name,
                    dimension=768,  # text-embedding-005 dimension
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                )
                logger.info(f"Created new Pinecone index: {self.index_name}")
            else:
                logger.info(f"Using existing Pinecone index: {self.index_name}")
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                logger.info(f"Index {self.index_name} already exists, continuing...")
            else:
                logger.error(f"Error creating Pinecone index: {str(e)}")
                raise

        self.index = pc.Index(self.index_name)

        # Initialize Google AI client
        os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv("FIREBASE_PROJECT_ID")
        os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv(
            "GOOGLE_CLOUD_LOCATION", "us-central1"
        )
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
        self.genai_client = genai.Client()

    def get_firebase_data(self) -> List[Dict[str, Any]]:
        """Fetch data from Firebase that needs to be synced."""
        # Get documents from the scraping_results collection
        if self.username:
            logger.info(f"Fetching data for username: {self.username}")
            # Try to get the specific document first
            doc_ref = self.db.collection("scraping_results").document(self.username)
            doc = doc_ref.get()

            if doc.exists:
                logger.info(f"Found document for username: {self.username}")
                doc_data = doc.to_dict()
                # Extract metadata array and create individual records
                metadata_array = doc_data.get("metadata", [])
                records = []
                for idx, metadata in enumerate(metadata_array):
                    record = {
                        "id": f"{doc.id}_{idx}",  # Create unique ID for each record
                        "username": self.username,
                        **metadata,  # Spread the metadata fields into the record
                    }
                    records.append(record)
                return records
            else:
                logger.info(f"No document found for username: {self.username}")
                return []
        else:
            logger.info("Fetching data for all usernames")
            docs = self.db.collection("scraping_results").stream()
            records = []
            for doc in docs:
                doc_data = doc.to_dict()
                metadata_array = doc_data.get("metadata", [])
                for idx, metadata in enumerate(metadata_array):
                    record = {"id": f"{doc.id}_{idx}", "username": doc.id, **metadata}
                    records.append(record)
            return records

    def create_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Create embeddings using Google's text-embedding-005 model."""
        try:
            logger.info(f"Creating embeddings for {len(texts)} texts")
            response = self.genai_client.models.embed_content(
                model="text-embedding-005",
                contents=texts,
                config=EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=768,
                ),
            )
            return [embedding.values for embedding in response.embeddings]
        except Exception as e:
            logger.error(f"Error creating embeddings: {str(e)}")
            raise

    def prepare_vectors(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare vectors for Pinecone from Firebase data."""
        vectors = []

        # Prepare texts for embedding
        texts_to_embed = []
        for item in data:
            # Combine content and caption for embedding
            content = item.get("ai_content_description", "")
            caption = item.get("caption", "")
            combined_text = f"content: {content} caption: {caption}"
            texts_to_embed.append(combined_text)

        # Create embeddings in batches to avoid rate limits
        batch_size = 10
        all_embeddings = []

        for i in range(0, len(texts_to_embed), batch_size):
            batch = texts_to_embed[i : i + batch_size]
            batch_embeddings = self.create_embeddings(batch)
            all_embeddings.extend(batch_embeddings)
            logger.info(
                f"Created embeddings for batch {i // batch_size + 1}/{(len(texts_to_embed) + batch_size - 1) // batch_size}"
            )

        # Create vectors with embeddings and metadata
        for i, item in enumerate(data):
            if i < len(all_embeddings):
                vector = {
                    "id": item["id"],
                    "values": all_embeddings[i],
                    "metadata": {
                        "username": item.get("username", ""),
                        "timestamp": item.get("timestamp").isoformat()
                        if item.get("timestamp")
                        else "",
                        "content": item.get("ai_content_description", ""),
                        "caption": item.get("caption", ""),
                        "last_updated": datetime.now().isoformat(),
                    },
                }
                vectors.append(vector)

        return vectors

    def sync_to_pinecone(self):
        """Main sync function to update Pinecone with Firebase data."""
        try:
            logger.info("Starting Pinecone sync...")
            data = self.get_firebase_data()

            if not data:
                logger.info("No data found in Firestore to sync")
                return

            logger.info(f"Found {len(data)} documents in Firestore")
            vectors = self.prepare_vectors(data)

            if vectors:
                # Upsert vectors in batches of 100
                batch_size = 100
                for i in range(0, len(vectors), batch_size):
                    batch = vectors[i : i + batch_size]
                    self.index.upsert(vectors=batch)
                    logger.info(f"Upserted batch of {len(batch)} vectors")

            logger.info("Pinecone sync completed successfully")
        except Exception as e:
            logger.error(f"Error during Pinecone sync: {str(e)}")
            raise


def run_sync_job(username: Optional[str] = None):
    """Function to run the sync job."""
    sync = PineconeSync(username=username)
    sync.sync_to_pinecone()


if __name__ == "__main__":
    run_sync_job()
