from io import BytesIO
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

import pymupdf
from PIL import Image

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
}


@contextmanager
def recognition_image(image_path):
    image_path = Path(image_path)

    if image_path.suffix.lower() in IMAGE_EXTENSIONS:
        yield image_path
        return

    if image_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Unsupported submission file type: "
            f"{image_path.suffix}"
        )

    document = pymupdf.open(image_path)

    try:
        page = document[0]

        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),
            alpha=False,
        )

        temporary_file = NamedTemporaryFile(
            suffix=".png",
            delete=False,
        )

        temporary_file.close()

        temporary_path = Path(
            temporary_file.name
        )

        pixmap.save(
            temporary_path
        )

        try:
            yield temporary_path
        finally:
            temporary_path.unlink(
                missing_ok=True
            )
    finally:
        document.close()

def crop_image(image_path, box):
    with Image.open(image_path) as image:
        cropped = image.crop(box).convert("RGB")

    buffer = BytesIO()
    cropped.save(buffer, format="PNG")

    return buffer.getvalue()