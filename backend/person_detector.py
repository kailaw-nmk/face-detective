"""人物検出モジュール。

YOLOv8 を使用して画像内の人物を検出し、人数をカウントする。
見開き分割の判定に使用する。
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_NAME = "yolov8n.pt"
_PERSON_CLASS_ID = 0
_MIN_CONFIDENCE = 0.3

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


def count_persons(image_array: np.ndarray) -> int:
    """画像内の人物数をカウントする。

    YOLOv8 で物体検出を行い、COCO の "person" クラス（ID=0）として
    検出されたバウンディングボックスの数を返す。

    Args:
        image_array: RGB 画像の numpy 配列（dtype=uint8）。

    Returns:
        検出された人物の数。エラー時は 0 を返す。
    """
    try:
        model = _get_model()
        results = model(image_array, verbose=False, conf=_MIN_CONFIDENCE)

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
