from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

import pymupdf


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
    #added this
    if image_path.stat().st_size == 0:
        raise ValueError(
            "PDF is empty"
        )
        #chnaged line 32 to 32-38 
    #document = pymupdf.open(image_path)
    # changed again 36-41
    try:
        document = pymupdf.open(image_path)
    except pymupdf.FileDataError as error:
        raise ValueError(
            "PDF is corrupt or invalid"
        ) from error
    
    if document.needs_pass:
        document.close()
        raise ValueError(
            "PDF is encrypted"
        )
    
    try:
        #page = document[0] only1 page or page 1 will be recognised 
        if document.page_count == 0:
            raise ValueError(
                "PDF contains no pages"
            )

        page = document[0]
            
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),#first PDF page into an image at roughly 2× scale.
            alpha=False,
        )
            #creates a temporary PNG:
        temporary_file = NamedTemporaryFile(
            suffix=".png",
            delete=False,
        )

        temporary_file.close()

        temporary_path = Path(
            temporary_file.name
        )
            #SAVE the rendered page
        pixmap.save(
            temporary_path
        )

        try:
            yield temporary_path #gives that PNG to the recognition process
        finally:
            temporary_path.unlink(
                missing_ok=True #deletes the temporary PNG
            )
    finally:
        document.close() # closes the PDF