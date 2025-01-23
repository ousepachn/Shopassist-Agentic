# Instagram Media Scraper

A Python-based Instagram media scraper that downloads images and videos from public Instagram profiles using the RapidAPI Instagram Scraper API. This tool supports downloading single images, videos, and carousel posts with pagination support.

## Features
- Download images and videos from public Instagram profiles
- Support for different types of posts:
  - Single images
  - Videos
  - Carousel/album posts
- Pagination support for fetching multiple posts
- Environment variable configuration for API keys
- Interactive command-line interface
- Organized output structure with timestamped folders

## Prerequisites
- Python 3.x
- RapidAPI Key (Instagram Scraper API)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/ousepachn/Shopassist-Agentic.git
cd Shopassist-Agentic
```

2. Install dependencies:
```bash
python3 -m pip install requests python-dotenv
```

3. Create a `.env` file in the project root and add your RapidAPI key:
```
RAPIDAPI_KEY=your_api_key_here
```

## Usage

Run the script:
```bash
python3 main.py
```

You will be prompted to:
- Enter an Instagram username (default: ousepachn)
- Enter number of posts to download (default: 6)

The media will be downloaded to a folder named `{username}_posts` in your project directory, with the following structure:
```
username_posts/
    username_timestamp/
        post_0_image.jpg      # Single image post
        post_1_video.mp4      # Video post
        post_2_album/         # Carousel post
            image_0.jpg
            image_1.jpg
            image_2.jpg
```

## Configuration
- Modify the default username and number of posts in `main.py`
- Adjust download delay settings in `instagram_scraper.py`
- Configure output directory structure in `process_profile()`

## Error Handling
The scraper includes error handling for:
- Invalid API keys
- Network issues
- Invalid usernames
- Download failures
- Rate limiting

## Contributing
Feel free to submit issues and enhancement requests!

## License
This project is licensed under the MIT License - see the LICENSE file for details. 