"""Fail early on overlapping cv2 wheels or an incompatible NumPy/OpenCV ABI."""

import json
from importlib.metadata import PackageNotFoundError, version


def check_runtime():
    distributions = (
        "opencv-python",
        "opencv-python-headless",
        "opencv-contrib-python",
        "opencv-contrib-python-headless",
    )
    installed = {}
    for name in distributions:
        try:
            installed[name] = version(name)
        except PackageNotFoundError:
            pass
    expected = {"opencv-contrib-python": "4.10.0.84"}
    if installed != expected:
        raise RuntimeError(
            f"Expected exactly {expected}; found {installed}. "
            "Recreate the environment from requirements.txt; overlapping wheels "
            "share cv2 files and cannot be repaired by uninstalling just one."
        )

    import cv2
    import numpy as np

    image = np.zeros((16, 16), dtype=np.uint8)
    image[4:12, 4:12] = 255
    encoded_ok, encoded = cv2.imencode(".png", image)
    if not encoded_ok:
        raise RuntimeError("OpenCV PNG encoding failed")
    decoded = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    np.testing.assert_array_equal(decoded, image)
    contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if len(contours) != 1 or cv2.__version__ != "4.10.0":
        raise RuntimeError("Unexpected OpenCV runtime or contour result")
    return {
        "opencv_distributions": installed,
        "cv2": cv2.__version__,
        "numpy": np.__version__,
        "paddleocr": version("paddleocr"),
        "paddlex": version("paddlex"),
        "paddlepaddle": version("paddlepaddle"),
        "abi_and_png_smoke_check": "passed",
    }


if __name__ == "__main__":
    print(json.dumps(check_runtime(), indent=2))
