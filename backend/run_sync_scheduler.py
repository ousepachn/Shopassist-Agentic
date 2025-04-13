import schedule
import time
import logging
import os
import argparse
from datetime import datetime
from services.pinecone_sync import run_sync_job
from dotenv import load_dotenv

# Load environment variables from .env.local
load_dotenv(".env.local")

# Configure logging
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_file = os.path.join(
    log_dir, f"pinecone_sync_{datetime.now().strftime('%Y%m%d')}.log"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def job(username=None):
    """Wrapper function to run the sync job with error handling."""
    try:
        logger.info("Starting scheduled sync job...")
        if username:
            logger.info(f"Processing data for username: {username}")
        start_time = time.time()
        run_sync_job(username=username)
        end_time = time.time()
        duration = end_time - start_time
        logger.info(
            f"Scheduled sync job completed successfully in {duration:.2f} seconds"
        )
    except Exception as e:
        logger.error(f"Error in scheduled sync job: {str(e)}", exc_info=True)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Pinecone Sync Scheduler")
    parser.add_argument(
        "--username", type=str, help="Username to filter data (optional)"
    )
    parser.add_argument(
        "--interval", type=int, default=4, help="Sync interval in hours (default: 4)"
    )
    parser.add_argument(
        "--run-once", action="store_true", help="Run once and exit (no scheduling)"
    )
    return parser.parse_args()


def main():
    """Main function to set up and run the scheduler."""
    args = parse_arguments()
    username = args.username
    interval = args.interval
    run_once = args.run_once

    logger.info("Starting Pinecone sync scheduler...")
    logger.info(
        f"Using Pinecone index: {os.getenv('PINECONE_INDEX_NAME', 'shopassist-v2')}"
    )
    logger.info(f"Using Google Cloud project: {os.getenv('FIREBASE_PROJECT_ID')}")

    if username:
        logger.info(f"Filtering data for username: {username}")

    if run_once:
        logger.info("Running in one-time mode (no scheduling)")
        job(username=username)
        return

    # Schedule the job to run at the specified interval
    schedule.every(interval).hours.do(job, username=username)
    logger.info(f"Scheduled sync job to run every {interval} hours")

    # Run the job immediately on startup
    logger.info("Running initial sync job...")
    job(username=username)

    # Keep the script running
    logger.info("Scheduler is running. Press Ctrl+C to exit.")
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)  # Check every minute for pending tasks
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in scheduler loop: {str(e)}", exc_info=True)
            # Wait a bit before retrying
            time.sleep(300)  # 5 minutes


if __name__ == "__main__":
    main()
