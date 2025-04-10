from instagram_scraper import InstagramScraper
import os
from dotenv import load_dotenv
import pandas as pd


def main():
    # Load environment variables
    load_dotenv()

    # Initialize scraper
    api_key = os.getenv("RAPIDAPI_KEY")
    scraper = InstagramScraper(api_key)

    # Process profile
    print("Processing profile...")
    df = scraper.process_profile("hydrationceo", max_posts=5)

    if df is not None:
        print("\nDataFrame Info:")
        print(df.info())

        print("\nDataFrame Columns:")
        print(df.columns.tolist())

        print("\nSample Data (first row):")
        first_row = df.iloc[0].to_dict()
        for key, value in first_row.items():
            print(f"{key}: {value}")

        print("\nTimestamps from posts:")
        for idx, row in df.iterrows():
            print(f"Post {row['post_id']}: Timestamp={row['timestamp']}")
            if "caption" in row and isinstance(row["caption"], dict):
                print(f"Raw caption data: {row['caption']}")

        # Update Firestore with new data
        print("\nUpdating Firestore...")
        from update_firestore import update_firestore_metadata

        update_firestore_metadata("hydrationceo")


if __name__ == "__main__":
    main()
