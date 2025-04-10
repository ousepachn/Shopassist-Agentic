import os
import sys
import pandas as pd
from google.cloud import firestore
from datetime import datetime
from dotenv import load_dotenv
from typing import Dict, List, Set
import pytest
import firebase_admin
from firebase_admin import credentials, firestore

# Add project root to path to import project modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)

from instagram_scraper import InstagramScraper


class TestMetadataConsistency:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test environment"""
        # Load environment variables from project's .env
        load_dotenv(os.path.join(project_root, ".env"))

        # Initialize Firebase Admin if not already initialized
        if not firebase_admin._apps:
            # Use existing service account from env
            service_account_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if not service_account_path:
                raise ValueError("GOOGLE_APPLICATION_CREDENTIALS not found in .env")

            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(
                cred, {"projectId": os.getenv("FIREBASE_PROJECT_ID")}
            )

        # Initialize Firestore
        self.db = firestore.client()

        # Initialize Instagram Scraper with API key from .env
        api_key = os.getenv("RAPIDAPI_KEY")
        if not api_key:
            raise ValueError("RAPIDAPI_KEY not found in .env")

        self.scraper = InstagramScraper(api_key)

        # Get test username from env or use default
        self.test_username = os.getenv("TEST_INSTAGRAM_USERNAME", "test_user")

    def get_expected_fields(self) -> Set[str]:
        """Define expected fields in both DataFrame and Firestore"""
        return {
            "permalink",
            "caption",
            "media_type",
            "timestamp",
            "ai_analysis",
            "ai_content_description",
            "ai_processed_time",
            "gcs_location",
            "username",
            "post_id",
        }

    def get_dataframe_fields(self, username: str) -> Set[str]:
        """Get fields from parquet file in GCS"""
        try:
            # Use the scraper's cloud storage handler
            metadata_path = f"instagram/{username}/metadata.parquet"
            df = self.scraper.cloud_storage.download_dataframe(metadata_path)
            if df is None:
                print(f"No parquet file found for {username}")
                return set()
            return set(df.columns)
        except Exception as e:
            print(f"Error reading parquet file: {e}")
            return set()

    def get_firestore_fields(self, username: str) -> Set[str]:
        """Get fields from Firestore document"""
        try:
            doc_ref = self.db.collection("scraping_results").document(username)
            doc = doc_ref.get()
            if doc.exists and doc.to_dict().get("metadata"):
                # Get fields from first metadata entry
                return set(doc.to_dict()["metadata"][0].keys())
            print(f"No Firestore document found for {username}")
            return set()
        except Exception as e:
            print(f"Error reading Firestore: {e}")
            return set()

    def compare_field_values(self, username: str) -> Dict:
        """Compare actual values between DataFrame and Firestore"""
        results = {
            "matching_posts": 0,
            "mismatched_posts": [],
            "field_value_differences": [],
        }

        try:
            # Get DataFrame from GCS
            df = self.scraper.cloud_storage.download_dataframe(
                f"instagram/{username}/metadata.parquet"
            )
            if df is None:
                print(f"No parquet file found for {username}")
                return results

            df_dict = df.to_dict("records")

            # Get Firestore data
            doc_ref = self.db.collection("scraping_results").document(username)
            doc = doc_ref.get()
            if not doc.exists:
                print(f"No Firestore document found for {username}")
                return results

            firestore_metadata = doc.to_dict()["metadata"]

            # Create lookup dictionary for Firestore posts
            firestore_lookup = {post["permalink"]: post for post in firestore_metadata}

            # Compare each post
            for df_post in df_dict:
                permalink = df_post.get("permalink")
                if permalink in firestore_lookup:
                    firestore_post = firestore_lookup[permalink]
                    results["matching_posts"] += 1

                    # Compare fields
                    for field in self.get_expected_fields():
                        df_value = df_post.get(field)
                        firestore_value = firestore_post.get(field)

                        # Handle timestamp comparison separately
                        if field == "timestamp":
                            if isinstance(df_value, pd.Timestamp):
                                df_value = df_value.to_pydatetime()
                            if isinstance(firestore_value, datetime):
                                firestore_value = firestore_value.replace(tzinfo=None)

                        if df_value != firestore_value:
                            results["field_value_differences"].append(
                                {
                                    "permalink": permalink,
                                    "field": field,
                                    "df_value": str(
                                        df_value
                                    ),  # Convert to string for comparison
                                    "firestore_value": str(firestore_value),
                                }
                            )
                else:
                    results["mismatched_posts"].append(
                        {"permalink": permalink, "source": "DataFrame"}
                    )

        except Exception as e:
            print(f"Error comparing values: {e}")
            import traceback

            traceback.print_exc()

        return results

    def test_field_consistency(self):
        """Test field consistency between DataFrame and Firestore"""
        expected_fields = self.get_expected_fields()
        df_fields = self.get_dataframe_fields(self.test_username)
        firestore_fields = self.get_firestore_fields(self.test_username)

        print("\nField Comparison:")
        print(f"Expected fields: {expected_fields}")
        print(f"DataFrame fields: {df_fields}")
        print(f"Firestore fields: {firestore_fields}")

        # Test DataFrame fields
        missing_in_df = expected_fields - df_fields
        assert not missing_in_df, f"Missing fields in DataFrame: {missing_in_df}"

        # Test Firestore fields
        missing_in_firestore = expected_fields - firestore_fields
        assert not missing_in_firestore, (
            f"Missing fields in Firestore: {missing_in_firestore}"
        )

        # Compare field values
        value_comparison = self.compare_field_values(self.test_username)

        # Print detailed results
        print("\nTest Results:")
        print(f"Matching posts found: {value_comparison['matching_posts']}")
        if value_comparison["field_value_differences"]:
            print("\nField value differences:")
            for diff in value_comparison["field_value_differences"]:
                print(f"\nPost: {diff['permalink']}")
                print(f"Field: {diff['field']}")
                print(f"DataFrame value: {diff['df_value']}")
                print(f"Firestore value: {diff['firestore_value']}")

        assert not value_comparison["field_value_differences"], (
            "Found differences in field values between DataFrame and Firestore"
        )

    def test_ai_content_description(self):
        """Specifically test ai_content_description field"""
        df = self.scraper.cloud_storage.download_dataframe(
            f"instagram/{self.test_username}/metadata.parquet"
        )
        doc_ref = self.db.collection("scraping_results").document(self.test_username)
        doc = doc_ref.get()

        if not doc.exists:
            pytest.fail("Firestore document not found")

        firestore_data = doc.to_dict()

        # Check DataFrame
        assert "ai_content_description" in df.columns, (
            "ai_content_description missing from DataFrame"
        )

        # Check Firestore
        assert firestore_data.get("metadata"), "No metadata in Firestore document"
        for post in firestore_data["metadata"]:
            assert "ai_content_description" in post, (
                f"ai_content_description missing for post {post.get('permalink', 'unknown')}"
            )
