from PIL import Image
import io
import math
from typing import List, Tuple
from google.cloud import storage
import tempfile
import os
import subprocess


class ImageGridProcessor:
    def __init__(self, bucket_name: str):
        """Initialize with GCS bucket name"""
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)

    def download_image_from_gcs(self, gcs_path: str) -> Image.Image:
        """Download an image from GCS and return as PIL Image"""
        blob = self.bucket.blob(gcs_path)
        image_data = blob.download_as_bytes()
        return Image.open(io.BytesIO(image_data))

    def upload_image_to_gcs(self, image: Image.Image, gcs_path: str):
        """Upload a PIL Image to GCS"""
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=95)
        buffer.seek(0)
        blob = self.bucket.blob(gcs_path)
        blob.upload_from_file(buffer, content_type="image/jpeg")

    def create_image_grid(
        self,
        image_paths: List[str],
        grid_size: Tuple[int, int] = (2, 2),
        max_width: int = 768,
        resampling_filter=Image.Resampling.LANCZOS,
    ) -> Image.Image:
        """Creates a grid of images with a maximum width and preserved aspect ratios.

        Args:
            image_paths: List of GCS paths to the images
            grid_size: Tuple (rows, cols) specifying the grid dimensions
            max_width: Maximum width of the grid in pixels
            resampling_filter: PIL resampling filter to use for resizing

        Returns:
            PIL Image object containing the grid
        """
        # Download and open images
        images = [self.download_image_from_gcs(path) for path in image_paths]
        widths, heights = zip(*(image.size for image in images))

        # Calculate target width for each image in the grid
        target_width = max_width // grid_size[1]  # Integer division

        # Resize images while maintaining aspect ratio
        resized_images = []
        for image, width, height in zip(images, widths, heights):
            if width > target_width:
                # Calculate new height based on the target width
                new_height = int(height * (target_width / width))
                image = image.resize((target_width, new_height), resampling_filter)
            resized_images.append(image)

        # Find maximum height after resizing
        max_height = max(img.height for img in resized_images)

        # Create the grid
        grid_image = Image.new(
            "RGB",
            (
                grid_size[1] * target_width,
                grid_size[0] * max_height,
            ),
            "white",  # White background
        )

        # Paste images into grid, centering vertically if needed
        for i, image in enumerate(resized_images):
            if i >= grid_size[0] * grid_size[1]:  # Don't exceed grid size
                break

            row = i // grid_size[1]
            col = i % grid_size[1]

            # Calculate vertical centering offset
            y_offset = (max_height - image.height) // 2

            # Paste image
            grid_image.paste(image, (col * target_width, row * max_height + y_offset))

        return grid_image

    def extract_video_frames(
        self, video_path: str, output_dir: str, interval: int = 2
    ) -> List[str]:
        """Extract frames from a video at specified intervals.

        Args:
            video_path: GCS path to the video
            output_dir: GCS path where to save the frames
            interval: Interval in seconds between frames

        Returns:
            List of GCS paths to the extracted frames
        """
        try:
            # Download video to temporary file
            with tempfile.NamedTemporaryFile(suffix=".mp4") as temp_video:
                blob = self.bucket.blob(video_path)
                blob.download_to_filename(temp_video.name)

                # Create temporary directory for frames
                with tempfile.TemporaryDirectory() as temp_dir:
                    # Extract frames using ffmpeg
                    frame_pattern = os.path.join(temp_dir, "frame_%d.jpg")
                    command = [
                        "ffmpeg",
                        "-i",
                        temp_video.name,
                        "-vf",
                        f"fps=1/{interval}",
                        "-frame_pts",
                        "1",
                        frame_pattern,
                    ]

                    result = subprocess.run(command, capture_output=True, text=True)
                    if result.returncode != 0:
                        print(f"[ERROR] Failed to extract frames: {result.stderr}")
                        return []

                    # Upload frames to GCS
                    frame_paths = []
                    for i, frame_file in enumerate(sorted(os.listdir(temp_dir))):
                        if frame_file.startswith("frame_"):
                            frame_path = f"{output_dir}/image_{i}.jpg"
                            with open(os.path.join(temp_dir, frame_file), "rb") as f:
                                self.bucket.blob(frame_path).upload_from_file(f)
                            frame_paths.append(frame_path)

                    return frame_paths[:4]  # Return only first 4 frames for 2x2 grid

        except Exception as e:
            print(f"[ERROR] Failed to extract video frames: {str(e)}")
            return []

    def process_album_images(
        self, album_path: str, num_images: int, grid_base_path: str
    ) -> List[str]:
        """Process album images into grids of 4 images each.

        Args:
            album_path: Base GCS path to the album folder
            num_images: Total number of images in the album
            grid_base_path: Base GCS path where to save the grid images

        Returns:
            List of GCS paths to the created grid images
        """
        grid_paths = []

        # Check if first item is a video
        first_item_path = f"{album_path}/image_0.mp4"
        if self.bucket.blob(first_item_path).exists():
            # Extract frames from video
            print("[INFO] First album item is a video, extracting frames...")
            frame_paths = self.extract_video_frames(first_item_path, album_path)

            if frame_paths:
                # Create grid from video frames
                grid_image = self.create_image_grid(
                    frame_paths, grid_size=(2, 2), max_width=768
                )

                # Save grid
                grid_path = f"{grid_base_path}/grid_0.jpg"
                self.upload_image_to_gcs(grid_image, grid_path)
                grid_paths.append(grid_path)

                # Process remaining images if any
                if num_images > 1:
                    remaining_paths = [
                        f"{album_path}/image_{i}.jpg" for i in range(1, num_images)
                    ]
                    remaining_grids = self._process_remaining_images(
                        remaining_paths, grid_base_path
                    )
                    grid_paths.extend(remaining_grids)

                return grid_paths

        # If first item is not a video or video processing failed, process normally
        return self._process_remaining_images(
            [f"{album_path}/image_{i}.jpg" for i in range(num_images)], grid_base_path
        )

    def _process_remaining_images(
        self, image_paths: List[str], grid_base_path: str
    ) -> List[str]:
        """Process remaining images in an album into grids.

        Args:
            image_paths: List of GCS paths to the images
            grid_base_path: Base GCS path where to save the grid images

        Returns:
            List of GCS paths to the created grid images
        """
        grid_paths = []
        num_grids = math.ceil(len(image_paths) / 4)

        for grid_idx in range(num_grids):
            # Get paths for current grid
            start_idx = grid_idx * 4
            end_idx = min(start_idx + 4, len(image_paths))
            current_paths = image_paths[start_idx:end_idx]

            # Create grid
            grid_image = self.create_image_grid(
                current_paths, grid_size=(2, 2), max_width=768
            )

            # Save grid
            grid_path = f"{grid_base_path}/grid_{grid_idx}.jpg"
            self.upload_image_to_gcs(grid_image, grid_path)
            grid_paths.append(grid_path)

        return grid_paths
