from instagram_scraper import CloudStorageHandler
import os


def main():
    # Initialize cloud storage handler
    bucket_name = "shopassist-agentic-media-data"
    cloud_storage = CloudStorageHandler(bucket_name)

    # Download metadata for rainbowplantlife
    username = "rainbowplantlife"
    metadata_path = f"instagram/{username}/metadata.parquet"

    print(f"Downloading metadata from {metadata_path}...")
    metadata_df = cloud_storage.download_dataframe(metadata_path)

    if metadata_df is None:
        print("Failed to download metadata")
        return

    # Save to CSV
    output_file = f"{username}_metadata.csv"
    metadata_df.to_csv(output_file, index=False)
    print(f"Metadata saved to {output_file}")


if __name__ == "__main__":
    main()
