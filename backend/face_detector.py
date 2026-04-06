"""顔検出モジュール。

MediaPipe Face Detection を使用して画像内の顔を検出し、
画像面積に対する最大顔面積の割合を計算する。

short-range モデル（Tasks API）で検出を行い、キーポイント（目・鼻・口）
および検出信頼度スコアを抽出する。
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
    both_eyes_visible: bool
    face_score: float


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
        both_eyes_visible=False,
        face_score=0.0,
    )


def _run_short_range(
    image_array: np.ndarray, image_width: int, image_height: int,
) -> list[tuple]:
    """short-range モデル（Tasks API）で顔検出を実行する。

    Args:
        image_array: RGB画像のnumpy配列。
        image_width: 画像の幅（ピクセル）。
        image_height: 画像の高さ（ピクセル）。

    Returns:
        検出された顔の (x, y, w, h, right_eye, left_eye, score) リスト。
        right_eye / left_eye は (px, py) ピクセル座標または None。
        score は検出信頼度（0〜1）。
    """
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_array)
    options = _FaceDetectorOptions(
        base_options=_BaseOptions(model_asset_path=str(_MODEL_PATH_SHORT)),
        min_detection_confidence=_MIN_DETECTION_CONFIDENCE,
    )
    with _FaceDetector.create_from_options(options) as detector:
        result = detector.detect(mp_image)

    faces = []
    for d in result.detections:
        x = d.bounding_box.origin_x
        y = d.bounding_box.origin_y
        w = d.bounding_box.width
        h = d.bounding_box.height
        right_eye = None
        left_eye = None
        if d.keypoints and len(d.keypoints) >= 2:
            kp0 = d.keypoints[0]
            kp1 = d.keypoints[1]
            right_eye = (kp0.x * image_width, kp0.y * image_height)
            left_eye = (kp1.x * image_width, kp1.y * image_height)
        score = d.categories[0].score if d.categories else 0.0
        faces.append((x, y, w, h, right_eye, left_eye, score))
    return faces


def detect_faces_from_array(
    image_array: np.ndarray,
    image_width: int,
    image_height: int,
    threshold: float,
    min_eye_ratio: float = 0.25,
    min_face_score: float = 0.5,
) -> FaceDetectionResult:
    """numpy配列として渡された画像から顔を検出し、面積比と移動判定を返す。

    面積比は「最大顔のバウンディングボックス面積 / 画像全体面積 × 100」で計算する。
    面積比が threshold 以上の場合、should_move が True となる。

    Args:
        image_array: RGB画像のnumpy配列（dtype=uint8）。
        image_width: 画像の幅（ピクセル）。
        image_height: 画像の高さ（ピクセル）。
        threshold: 移動判定に使用する面積比の閾値（0〜100）。
        min_eye_ratio: 両目間距離 / 顔幅 の最小比率。これ未満は横顔とみなす。
        min_face_score: 両目可視判定に必要な最低検出信頼度（0〜1）。

    Returns:
        検出結果を含む FaceDetectionResult 辞書。
    """
    try:
        image_area = image_width * image_height
        if image_area == 0:
            logger.warning("画像面積が0です (width=%d, height=%d)", image_width, image_height)
            return _no_face_result()

        faces = _run_short_range(image_array, image_width, image_height)

        if not faces:
            logger.debug("顔が検出されませんでした")
            return _no_face_result()

        face_count = len(faces)

        # 最大面積の顔を特定する
        max_face_idx = max(
            range(len(faces)), key=lambda i: faces[i][2] * faces[i][3]
        )
        max_face = faces[max_face_idx]
        _, _, w, h, right_eye, left_eye, score = max_face

        max_face_area = w * h
        max_face_ratio = (max_face_area / image_area) * 100.0
        should_move = max_face_ratio >= threshold

        # 両目可視の判定: 信頼度スコアと目の距離の両方をチェック
        both_eyes_visible = False
        if right_eye is not None and left_eye is not None and score >= min_face_score:
            eye_dist = abs(right_eye[0] - left_eye[0])
            both_eyes_visible = (eye_dist / w) > min_eye_ratio if w > 0 else False

        logger.debug(
            "顔検出完了 — 顔数=%d, 最大面積比=%.2f%%, 移動=%s, 両目=%s, 信頼度=%.2f",
            face_count,
            max_face_ratio,
            should_move,
            both_eyes_visible,
            score,
        )

        return FaceDetectionResult(
            has_face=True,
            max_face_ratio=max_face_ratio,
            face_count=face_count,
            should_move=should_move,
            both_eyes_visible=both_eyes_visible,
            face_score=score,
        )

    except Exception as exc:
        logger.error("顔検出中にエラーが発生しました — %s", exc, exc_info=True)
        return _no_face_result()


def detect_faces(
    image_path: Path,
    threshold: float,
    min_eye_ratio: float = 0.25,
    min_face_score: float = 0.5,
) -> FaceDetectionResult:
    """画像ファイルから顔を検出し、面積比と移動判定を返す。

    画像ファイルを開いてRGB numpy配列に変換したうえで
    :func:`detect_faces_from_array` に処理を委譲する。

    Args:
        image_path: 検出対象の画像ファイルパス。
        threshold: 移動判定に使用する面積比の閾値（0〜100）。
        min_eye_ratio: 両目間距離 / 顔幅 の最小比率。
        min_face_score: 両目可視判定に必要な最低検出信頼度（0〜1）。

    Returns:
        検出結果を含む FaceDetectionResult 辞書。
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

    result = detect_faces_from_array(
        image_array, image_width, image_height, threshold,
        min_eye_ratio=min_eye_ratio,
        min_face_score=min_face_score,
    )

    if result["has_face"]:
        logger.debug(
            "顔検出完了: %s — 顔数=%d, 最大面積比=%.2f%%, 移動=%s, 信頼度=%.2f",
            image_path,
            result["face_count"],
            result["max_face_ratio"],
            result["should_move"],
            result["face_score"],
        )
    else:
        logger.debug("顔が検出されませんでした: %s", image_path)

    return result
