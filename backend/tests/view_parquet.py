#!/usr/bin/env python3
import pandas as pd
from google.cloud import storage
import argparse
import os
from datetime import datetime


def view_parquet(influencer_name: str, output_dir: str = "/tmp"):
    """
    View and analyze parquet file for a given influencer.

    Args:
        influencer_name: Name of the influencer
        output_dir: Directory to save output files (default: /tmp)
    """
    # Initialize the client
    storage_client = storage.Client()

    # Get the bucket and blob
    bucket = storage_client.bucket("shopassist-agentic-media-data")
    blob = bucket.blob(f"instagram/{influencer_name}/metadata.parquet")

    # Create timestamp for unique filenames
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Download to a temporary file
    local_path = os.path.join(
        output_dir, f"metadata_{influencer_name}_{timestamp}.parquet"
    )
    blob.download_to_filename(local_path)

    # Read the parquet file
    df = pd.read_parquet(local_path)

    # Display information about the DataFrame
    print("\nDataFrame Info:")
    print(df.info())

    print("\nFirst few rows:")
    print(df.head())

    print("\nTimestamp column info:")
    print(df["timestamp"].head())
    print("\nTimestamp dtype:", df["timestamp"].dtype)

    # Export to CSV
    csv_path = os.path.join(output_dir, f"metadata_{influencer_name}_{timestamp}.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nDataFrame exported to CSV at: {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="View parquet file for an Instagram influencer"
    )
    parser.add_argument(
        "influencer_name", help="Name of the influencer (e.g., beckybarnicomics)"
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp",
        help="Directory to save output files (default: /tmp)",
    )

    args = parser.parse_args()

    try:
        view_parquet(args.influencer_name, args.output_dir)
    except Exception as e:
        print(f"Error: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()
