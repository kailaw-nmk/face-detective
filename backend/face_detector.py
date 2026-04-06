"""顔検出モジュール。

MediaPipe Face Detection を使用して画像内の顔を検出し、
画像面積に対する最大顔面積の割合を計算する。

short-range モデル（Tasks API）で検出を試み、顔が見つからない場合は
full-range モデル（Solutions API, model_selection=1）でフォールバック検出を行う。
"""

import logging
from pathlib import Path
from typing import TypedDict

import mediapipe as mp
import numpy as np
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

logger = logging.getLogger(__name__)

_MODEL_PATH_SHORT = Path(__file__).parent / "blaze_face_short_range.tflite"

_BaseOptions = mp.tasks.BaseOptions
_FaceDetector = mp.tasks.vision.FaceDetector
_FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions

_MIN_DETECTION_CONFIDENCE = 0.4


class FaceDetectionResult(TypedDict):
    """顔検出結果の型定義。"""

    has_face: bool
    max_face_ratio: float
    face_count: int
    should_move: bool


def _no_face_result(should_move: bool = False) -> FaceDetectionResult:
    """顔なし結果の辞書を生成するヘルパー関数。

    Args:
        should_move: 移動対象フラグ（デフォルト False）。

    Returns:
        顔なしを示す FaceDetectionResult。
    """
    return FaceDetectionResult(
        has_face=False,
        max_face_ratio=0.0,
        face_count=0,
        should_move=should_move,
    )


def _run_short_range(image_array: np.ndarray) -> list[tuple[float, float, float, float]]:
    """short-range モデル（Tasks API）で顔検出を実行する。

    Args:
        image_array: RGB画像のnumpy配列。

    Returns:
        検出された顔の (x, y, width, height) ピクセル座標リスト。
    """
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_array)
    options = _FaceDetectorOptions(
        base_options=_BaseOptions(model_asset_path=str(_MODEL_PATH_SHORT)),
        min_detection_confidence=_MIN_DETECTION_CONFIDENCE,
    )
    with _FaceDetector.create_from_options(options) as detector:
        result = detector.detect(mp_image)

    return [
        (d.bounding_box.origin_x, d.bounding_box.origin_y,
         d.bounding_box.width, d.bounding_box.height)
        for d in result.detections
    ]


def _run_full_range(image_array: np.ndarray, image_width: int, image_height: int) -> list[tuple[float, float, float, float]]:
    """full-range モデル（Solutions API, model_selection=1）で顔検出を実行する。

    Solutions API は正規化座標（0〜1）を返すため、ピクセル座標に変換する。

    Args:
        image_array: RGB画像のnumpy配列。
        image_width: 画像の幅（ピクセル）。
        image_height: 画像の高さ（ピクセル）。

    Returns:
        検出された顔の (x, y, width, height) ピクセル座標リスト。
    """
    with mp.solutions.face_detection.FaceDetection(
        model_selection=1,
        min_detection_confidence=_MIN_DETECTION_CONFIDENCE,
    ) as detector:
        result = detector.process(image_array)

    if not result.detections:
        return []

    faces = []
    for detection in result.detections:
        bbox = detection.location_data.relative_bounding_box
        x = bbox.xmin * image_width
        y = bbox.ymin * image_height
        w = bbox.width * image_width
        h = bbox.height * image_height
        faces.append((x, y, w, h))
    return faces


def detect_faces_from_array(
    image_array: np.ndarray,
    image_width: int,
    image_height: int,
    threshold: float,
) -> FaceDetectionResult:
    """numpy配列として渡された画像から顔を検出し、面積比と移動判定を返す。

    面積比は「最大顔のバウンディングボックス面積 / 画像全体面積 × 100」で計算する。
    面積比が threshold 以上の場合、should_move が True となる。

    short-range モデルで検出を試み、顔が見つからない場合は
    full-range モデルでフォールバック検出を行う。

    Args:
        image_array: RGB画像のnumpy配列（dtype=uint8）。
        image_width: 画像の幅（ピクセル）。
        image_height: 画像の高さ（ピクセル）。
        threshold: 移動判定に使用する面積比の閾値（0〜100）。

    Returns:
        検出結果を含む辞書:
            - has_face (bool): 顔が1件以上検出されたか。
            - max_face_ratio (float): 最大顔面積比 (%)。
            - face_count (int): 検出された顔の数。
            - should_move (bool): 面積比が閾値以上かどうか。
    """
    try:
        image_area = image_width * image_height
        if image_area == 0:
            logger.warning("画像面積が0です (width=%d, height=%d)", image_width, image_height)
            return _no_face_result()

        faces = _run_short_range(image_array)

        if not faces:
            logger.debug("short-rangeで未検出、full-rangeで再試行します")
            faces = _run_full_range(image_array, image_width, image_height)

        if not faces:
            logger.debug("顔が検出されませんでした")
            return _no_face_result()

        face_count = len(faces)
        max_face_area = max(w * h for _, _, w, h in faces)
        max_face_ratio = (max_face_area / image_area) * 100.0
        should_move = max_face_ratio >= threshold

        logger.debug(
            "顔検出完了 — 顔数=%d, 最大面積比=%.2f%%, 移動=%s",
            face_count,
            max_face_ratio,
            should_move,
        )

        return FaceDetectionResult(
            has_face=True,
            max_face_ratio=max_face_ratio,
            face_count=face_count,
            should_move=should_move,
        )

    except Exception as exc:
        logger.error("顔検出中にエラーが発生しました — %s", exc, exc_info=True)
        return _no_face_result()


def detect_faces(image_path: Path, threshold: float) -> FaceDetectionResult:
    """画像ファイルから顔を検出し、面積比と移動判定を返す。

    画像ファイルを開いてRGB numpy配列に変換したうえで
    :func:`detect_faces_from_array` に処理を委譲する。

    Args:
        image_path: 検出対象の画像ファイルパス。
        threshold: 移動判定に使用する面積比の閾値（0〜100）。

    Returns:
        検出結果を含む辞書:
            - has_face (bool): 顔が1件以上検出されたか。
            - max_face_ratio (float): 最大顔面積比 (%)。
            - face_count (int): 検出された顔の数。
            - should_move (bool): 面積比が閾値以上かどうか。
    """
    try:
        with Image.open(image_path) as img:
            rgb_image = img.convert("RGB")
            image_width, image_height = rgb_image.size
            image_array = np.array(rgb_image, dtype=np.uint8)
    except Exception as exc:
        logger.error(
            "画像の読み込みに失敗しました: %s — %s", image_path, exc, exc_info=True
        )
        return _no_face_result()

    result = detect_faces_from_array(image_array, image_width, image_height, threshold)

    if result["has_face"]:
        logger.debug(
            "顔検出完了: %s — 顔数=%d, 最大面積比=%.2f%%, 移動=%s",
            image_path,
            result["face_count"],
            result["max_face_ratio"],
            result["should_move"],
        )
    else:
        logger.debug("顔が検出されませんでした: %s", image_path)

    return result
