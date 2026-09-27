from pathlib import Path

import cv2
from submissions.recognition.types import ImageQualityResult

def calculate_blur_score(image_path):
    image_path = Path(image_path)

    image = cv2.imread(
        str(image_path),
        cv2.IMREAD_GRAYSCALE,
    )

    if image is None:
        raise ValueError(
            "Unable to read image"
        )

    return cv2.Laplacian(
        image,
        cv2.CV_64F,
    ).var()

     #Resolution Measurement
def get_image_resolution(image_path):
    image_path = Path(image_path)
    
    image = cv2.imread(
        str(image_path)
    )
    
    if image is None:
        raise ValueError(
            "Unable to read image"
    )
    
    height, width = image.shape[:2]
    
    return width, height

def calculate_brightness(image_path):
    image_path = Path(image_path)

    image = cv2.imread(
        str(image_path),
        cv2.IMREAD_GRAYSCALE,
    )

    if image is None:
        raise ValueError(
            "Unable to read image"
        )

    return image.mean()

def calculate_contrast(image_path):
    image_path = Path(image_path)

    image = cv2.imread(
        str(image_path),
        cv2.IMREAD_GRAYSCALE,
    )

    if image is None:
        raise ValueError(
            "Unable to read image"
        )

    return image.std()

def assess_image_quality(image_path):
    image_path = Path(image_path)

    blur_score = calculate_blur_score(
        image_path
    )

    width, height = get_image_resolution(
        image_path
    )

    brightness = calculate_brightness(
        image_path
    )

    contrast = calculate_contrast(
        image_path
    )

    # Reject severely low-resolution scans.
    if min(width, height) < 500:
        return ImageQualityResult(
            usable=False,
            reason="Image resolution is too low",
        )

    # Representative readable scans scored above 200.
    # Keep this threshold conservative to avoid rejecting
    # slightly soft but still usable scans.
    if blur_score < 20:
        return ImageQualityResult(
            usable=False,
            reason="Image is too blurry",
        )

    # Detect severe underexposure.
    if brightness < 80:
        return ImageQualityResult(
            usable=False,
            reason="Image is too dark",
        )

    # Detect severe overexposure.
    if brightness > 230:
        return ImageQualityResult(
            usable=False,
            reason="Image is too bright",
        )

    # Detect images with very little separation
    # between light and dark areas.
    if contrast < 15:
        return ImageQualityResult(
            usable=False,
            reason="Image contrast is too low",
        )

    return ImageQualityResult(
        usable=True,
        reason=None,
    )