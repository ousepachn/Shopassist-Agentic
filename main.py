from instagram_scraper import InstagramScraper
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

    # Get username from user input
    username = get_user_input("Enter Instagram username", "ousepachn")

    # Get number of posts from user input
    max_posts_str = get_user_input("Enter number of posts to download", "6")
    try:
        max_posts = int(max_posts_str)
    except ValueError:
        print(f"Invalid number '{max_posts_str}', using default: 6")
        max_posts = 6

    # Initialize scraper
    scraper = InstagramScraper(api_key)

    # Create project folder
    project_folder = f"{username}_posts"
    if not os.path.exists(project_folder):
        os.makedirs(project_folder)

    # Get and display metadata
    print(f"\nFetching metadata for {max_posts} posts from {username}")
    metadata_df = scraper.process_profile(username, project_folder, max_posts)

    if metadata_df is not None:
        # Ask user if they want to download media
        download_choice = get_user_input(
            "\nDo you want to download the media files? (yes/no)", "no"
        )

        if download_choice.lower() in ["y", "yes"]:
            print("\nStarting media download...")
            scraper.download_media_from_metadata(metadata_df, project_folder)
            print("\nDownload completed!")
            print(f"Check the '{project_folder}' directory for downloaded content")
        else:
            print("\nSkipping media download.")
    else:
        print("No metadata available for download.")


if __name__ == "__main__":
    main()
