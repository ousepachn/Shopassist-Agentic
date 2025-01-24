# Instagram Media Scraper

A Python-based Instagram media scraper that downloads images and videos from public Instagram profiles using the RapidAPI Instagram Scraper API. This tool supports downloading single images, videos, and carousel posts with pagination support, and includes AI-powered content analysis using Google Cloud Vertex AI.

## Features
- Download images and videos from public Instagram profiles
- Support for different types of posts:
  - Single images
  - Videos
  - Carousel/album posts
- AI-powered content analysis using Google Cloud Vertex AI
- Pagination support for fetching multiple posts
- Environment variable configuration for API keys
- Interactive command-line interface
- Organized output structure with cloud storage integration

## Prerequisites
- Python 3.x
- RapidAPI Key (Instagram Scraper API)
- Google Cloud Project with:
  - Vertex AI API enabled
  - Cloud Storage bucket
  - Service account with appropriate permissions

## Installation

1. Clone the repository:
```bash
git clone https://github.com/ousepachn/Shopassist-Agentic.git
cd Shopassist-Agentic
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Unix/macOS
venv\Scripts\activate     # On Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root and add your API keys:
```
RAPIDAPI_KEY=your_api_key_here
```

5. Set up Google Cloud credentials:
   - Create a service account in your Google Cloud project
   - Download the service account key JSON file
   - Set the GOOGLE_APPLICATION_CREDENTIALS environment variable:
```bash
export GOOGLE_APPLICATION_CREDENTIALS="path/to/service-account-key.json"
```

## Usage

There are two ways to use the scraper:

### 1. Basic Scraper (main.py)
This is the simple version that downloads media files locally:

```bash
python3 main.py
```

You will be prompted to:
- Enter an Instagram username (default: ousepachn)
- Enter number of posts to download (default: 6)

The media will be downloaded to a folder named `{username}_posts` in your project directory.

### 2. Advanced Scraper with AI (run_scraper.py)
This version includes cloud storage integration and AI-powered content analysis:

```bash
# To scrape posts and analyze content
./run_scraper.py -M scrape -u <username> -m <max_posts>

# To run AI analysis on previously scraped posts
./run_scraper.py -M ai -u <username>
```

Options:
- `-M, --mode`: Operation mode (`scrape` or `ai`)
- `-u, --username`: Instagram username to process
- `-m, --max-posts`: Maximum number of posts to scrape (default: 50)

Example:
```bash
# Scrape 10 posts from Nike's profile
./run_scraper.py -M scrape -u nike -m 10

# Run AI analysis on previously scraped posts
./run_scraper.py -M ai -u nike
```

## Output Structure

### Local Storage (main.py)
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

### Cloud Storage (run_scraper.py)
```
instagram/
    username/
        media/
            post_ABC123_image.jpg     # Single image post
            post_DEF456_video.mp4     # Video post
            post_GHI789_album/        # Carousel post
                image_0.jpg
                image_1.jpg
        metadata.parquet              # Post metadata and AI analysis
```

## AI Analysis
The tool uses Google Cloud Vertex AI to analyze media content:
- Image analysis includes:
  - Detailed description
  - Style and mood analysis
  - Text detection
  - Safety assessment
- Video analysis (coming soon)
- Album analysis processes each image individually

## Error Handling
The scraper includes error handling for:
- Invalid API keys
- Network issues
- Invalid usernames
- Download failures
- Rate limiting
- Cloud storage issues
- AI processing errors

## Contributing
Feel free to submit issues and enhancement requests!

## License
This project is licensed under the MIT License - see the LICENSE file for details. 