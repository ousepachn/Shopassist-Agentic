import pandas as pd
from google.cloud import storage

# Initialize GCS client
storage_client = storage.Client()
bucket = storage_client.bucket("shopassist-agentic-media-data")
blob = bucket.blob("instagram/whatsmitafound/metadata.parquet")

# Download the file to a temporary location
local_path = "/tmp/metadata.parquet"
blob.download_to_filename(local_path)

# Read the parquet file
df = pd.read_parquet(local_path)

print("\nDataFrame Info:")
print(df.info())

print("\nTimestamp column info:")
print(df["timestamp"].describe())

print("\nTimestamp values:")
for idx, row in df.iterrows():
    print(f"{row.post_id}: {row.timestamp} ({type(row.timestamp)})")

print("\nSample Data:")
print(df[["post_id", "timestamp", "media_type", "media_urls", "gcs_location"]].head())
