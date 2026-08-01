from pathlib import Path

import cv2
import numpy as np


def decode_image(image_path: Path) -> np.ndarray:
    """Decode via bytes so Chinese Windows paths work reliably with OpenCV."""
    data = np.fromfile(str(image_path), dtype=np.uint8)
    if data.size == 0:
        raise ValueError("图片文件为空。")
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError("图片无法解码。")
    return image


def to_grayscale(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

