import pandas as pd
from google.cloud import storage

# Initialize the client
storage_client = storage.Client()

# Get the bucket and blob
bucket = storage_client.bucket("shopassist-agentic-media-data")
blob = bucket.blob("instagram/beckybarnicomics/metadata.parquet")
# Download to a temporary file
local_path = "/tmp/metadata.parquet"
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
csv_path = "/tmp/metadata.csv"
df.to_csv(csv_path, index=False)
print(f"\nDataFrame exported to CSV at: {csv_path}")
