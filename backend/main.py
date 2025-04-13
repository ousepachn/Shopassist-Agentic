from scrapers.instagram_scraper import InstagramScraper
import os
from dotenv import load_dotenv


def get_user_input(prompt: str, default: str) -> str:
    """Get user input with a default value"""
    user_input = input(f"{prompt} (default: {default}): ").strip()
    return user_input if user_input else default


def main():
    # Load environment variables
    load_dotenv()

    # Get API key from environment variable
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        print("Error: RAPIDAPI_KEY not found in .env file")
        return

    # Check for Google Cloud credentials
    google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not google_creds:
        print("Error: GOOGLE_APPLICATION_CREDENTIALS not found in environment")
        print("Please set up your Google Cloud credentials first:")
        print("1. Go to Google Cloud Console > IAM & Admin > Service Accounts")
        print("2. Create a service account or select existing one")
        print("3. Create a new JSON key")
        print(
            "4. Set the path to the JSON file in GOOGLE_APPLICATION_CREDENTIALS environment variable"
        )
        return

    if not os.path.exists(google_creds):
        print(f"Error: Google Cloud credentials file not found at: {google_creds}")
        return

    # Get username from user input
    username = get_user_input("Enter Instagram username", "ousepachn")

    # Get number of posts from user input
    max_posts_str = get_user_input("Enter number of posts to download", "6")
    try:
        max_posts = int(max_posts_str)
    except ValueError:
        print(f"Invalid number '{max_posts_str}', using default: 6")
        max_posts = 6

    # Initialize scraper with cloud storage
    scraper = InstagramScraper(api_key)

    # Get and display metadata
    print(f"\nFetching metadata for {max_posts} posts from {username}")
    metadata_df = scraper.process_profile(username, max_posts)

    if metadata_df is not None:
        # Ask user if they want to download media
        download_choice = get_user_input(
            "\nDo you want to download the media files to cloud storage? (yes/no)", "no"
        )

        if download_choice.lower() in ["y", "yes"]:
            print("\nStarting media upload to cloud storage...")
            scraper.download_media_from_metadata(metadata_df, username)
            print("\nUpload completed!")
            print("Check the cloud storage bucket for uploaded content")
        else:
            print("\nSkipping media download.")
    else:
        print("No metadata available for download.")


if __name__ == "__main__":
    main()
