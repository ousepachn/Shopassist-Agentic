from PIL import Image
import io
import math
from typing import List, Tuple
from google.cloud import storage


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

        # Calculate number of grids needed
        num_grids = math.ceil(num_images / 4)

        for grid_idx in range(num_grids):
            # Get paths for current grid
            start_idx = grid_idx * 4
            end_idx = min(start_idx + 4, num_images)

            image_paths = [
                f"{album_path}/image_{i}.jpg" for i in range(start_idx, end_idx)
            ]

            # Create grid
            grid_image = self.create_image_grid(
                image_paths, grid_size=(2, 2), max_width=768
            )

            # Save grid
            grid_path = f"{grid_base_path}/grid_{grid_idx}.jpg"
            self.upload_image_to_gcs(grid_image, grid_path)
            grid_paths.append(grid_path)

        return grid_paths
