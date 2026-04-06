"""人物検出モジュール。

YOLOv8 を使用して画像内の人物を検出し、人数をカウントする。
見開き分割の判定に使用する。
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_NAME = "yolov8s.pt"
_PERSON_CLASS_ID = 0
_DEFAULT_CONFIDENCE = 0.2

# モデルはモジュール初回使用時に遅延ロードする
_model = None


def _get_model():
    """YOLOv8 モデルを遅延ロードして返す。

    初回呼び出し時にモデルをロードし、以降はキャッシュを返す。
    モデルファイルが存在しない場合は自動ダウンロードされる。

    Returns:
        ロード済みの YOLO モデルインスタンス。
    """
    global _model
    if _model is None:
        from ultralytics import YOLO

        logger.info("YOLOv8 モデルをロード中: %s", _MODEL_NAME)
        _model = YOLO(_MODEL_NAME)
        logger.info("YOLOv8 モデルのロード完了")
    return _model


def count_persons(image_array: np.ndarray, confidence: float = _DEFAULT_CONFIDENCE) -> int:
    """画像内の人物数をカウントする。

    YOLOv8 で物体検出を行い、COCO の "person" クラス（ID=0）として
    検出されたバウンディングボックスの数を返す。

    Args:
        image_array: RGB 画像の numpy 配列（dtype=uint8）。
        confidence: YOLO の検出信頼度閾値（0〜1）。

    Returns:
        検出された人物の数。エラー時は 0 を返す。
    """
    try:
        model = _get_model()
        results = model(image_array, verbose=False, conf=confidence)

        person_count = 0
        for result in results:
            for box in result.boxes:
                if int(box.cls[0]) == _PERSON_CLASS_ID:
                    person_count += 1

        logger.debug("人物検出完了 — 検出数=%d", person_count)
        return person_count

    except Exception as exc:
        logger.error("人物検出中にエラーが発生しました — %s", exc, exc_info=True)
        return 0


def count_persons_split(image_array: np.ndarray, confidence: float = _DEFAULT_CONFIDENCE) -> int:
    """画像を左右に分割してそれぞれ人物検出し、合計数を返す。

    見開き画像の分割判定を改善するため、左右半分ごとに独立して
    人物検出を行う。各半分で1人以上検出されたら「その側に人物あり」
    とカウントする。

    Args:
        image_array: RGB 画像の numpy 配列（dtype=uint8）。
        confidence: YOLO の検出信頼度閾値（0〜1）。

    Returns:
        左右それぞれで1人以上検出された側の数（0, 1, or 2）。
    """
    try:
        h, w = image_array.shape[:2]
        mid = w // 2

        left_half = image_array[:, :mid, :]
        right_half = image_array[:, mid:, :]

        left_count = count_persons(left_half, confidence)
        right_count = count_persons(right_half, confidence)

        total = (1 if left_count >= 1 else 0) + (1 if right_count >= 1 else 0)

        logger.debug(
            "左右分割検出 — 左=%d, 右=%d, 合計=%d",
            left_count, right_count, total,
        )
        return total

    except Exception as exc:
        logger.error("左右分割人物検出中にエラーが発生しました — %s", exc, exc_info=True)
        return 0
