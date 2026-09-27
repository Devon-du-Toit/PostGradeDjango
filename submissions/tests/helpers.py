import shutil
import tempfile
from io import BytesIO

from django.test import override_settings
from PIL import Image


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class TemporaryMediaMixin:
    """Stores uploaded and generated files in a temporary folder.

    The folder is deleted after the test class, because destroying the test
    database does not remove files written to MEDIA_ROOT.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.media_root = tempfile.mkdtemp(prefix="postgrade-test-media-")
        cls.addClassCleanup(shutil.rmtree, cls.media_root, ignore_errors=True)
        cls.enterClassContext(override_settings(MEDIA_ROOT=cls.media_root))


def make_png(width=40, height=10):
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()
