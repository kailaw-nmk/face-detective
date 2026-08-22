"""余白トリミングモジュール。

画像の四辺にある均一な白／黒の余白帯を検出し、コンテンツ領域のみを切り出す。

電子書籍リーダーのスクリーンショットには、リーダー UI（ライブラリボタン・タイトル・
ページ送り矢印・プログレスバー）が白背景ごと写り込んでおり、画像面積の大半を余白が
占めることがある。この余白は顔面積比の分母を膨らませ、閾値判定を不正確にする。

検出方針:
    1. 「白でも黒でもない画素」のマスクを作る
    2. モルフォロジー開処理で JPEG のリンギングと細い文字を除去する
    3. 連結成分を求め、面積比が一定以上のものだけを採用する
    4. 採用した全成分の外接矩形の和を取る

最大成分ではなく「全成分の外接矩形の和」を取るのが要点である。誌面が複数のブロックに
分かれるレイアウトでは、最大成分だけを残すと他のブロックを捨ててしまう。和を取れば
削られるのは四辺の均一な余白帯だけになり、内容の欠落が原理的に起きない。
"""

import logging
from typing import TypedDict

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# 余白判定パラメータ
WHITE_THRESHOLD = 240.0        # これより明るい画素は余白候補（0–255）
BLACK_THRESHOLD = 15.0         # これより暗い画素は余白候補（0–255）
MIN_COMPONENT_AREA_RATIO = 0.002  # 画像面積比 0.2% 未満の成分は UI 部品とみなし無視
OPEN_KERNEL_SIZE = 9           # モルフォロジー開処理のカーネル一辺（px）

# 安全弁パラメータ
MIN_KEEP_AREA_RATIO = 0.05     # 残率がこれ未満ならトリミングを中止する
MIN_OUTPUT_SIZE = 32           # 出力の幅または高さがこれ未満ならトリミングを中止する


class TrimResult(TypedDict):
    """余白トリミング結果の型定義。"""

    trimmed: bool                     # 実際にトリミングしたかどうか
    bbox: tuple[int, int, int, int]   # (left, top, right, bottom)。right/bottom は exclusive
    keep_ratio: float                 # 残存面積比 (0.0–1.0)
    reason: str                       # "trimmed"|"no_margin"|"no_content"|"too_aggressive"|"too_small"|"error"


def detect_content_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    """余白を除いたコンテンツ領域の外接矩形を検出する。

    白でも黒でもない画素を「コンテンツ」とみなし、モルフォロジー開処理でノイズと
    細い文字を落としたうえで連結成分を求める。面積比が
    ``MIN_COMPONENT_AREA_RATIO`` 以上の成分をすべて採用し、その外接矩形の和を返す。

    Args:
        image: 処理対象の PIL 画像。RGB 以外のモードでも受け付ける。

    Returns:
        コンテンツ領域の (left, top, right, bottom)。right/bottom は exclusive。
        有効な成分が 1 つもない場合は None。
    """
    rgb = image.convert("RGB")
    # (H, W, 3) の float32 中間バッファを作らずに輝度を求める。
    # 大きな画像でのメモリスパイクを避けるため、uint8 のまま mean の累積型だけ float32 にする。
    arr = np.asarray(rgb, dtype=np.uint8)         # shape: (H, W, 3)
    luminance = arr.mean(axis=2, dtype=np.float32)  # shape: (H, W)
    height, width = luminance.shape

    margin_mask = (luminance > WHITE_THRESHOLD) | (luminance < BLACK_THRESHOLD)
    content_mask = (~margin_mask).astype(np.uint8)

    kernel = np.ones((OPEN_KERNEL_SIZE, OPEN_KERNEL_SIZE), np.uint8)
    content_mask = cv2.morphologyEx(content_mask, cv2.MORPH_OPEN, kernel)

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        content_mask, connectivity=8
    )

    total_area = float(width * height)
    # index 0 は背景成分なので除外する
    kept = [
        stats[i]
        for i in range(1, count)
        if stats[i][cv2.CC_STAT_AREA] / total_area >= MIN_COMPONENT_AREA_RATIO
    ]

    if not kept:
        logger.debug("有効なコンテンツ成分がありません (画像サイズ %dx%d)", width, height)
        return None

    left = int(min(s[cv2.CC_STAT_LEFT] for s in kept))
    top = int(min(s[cv2.CC_STAT_TOP] for s in kept))
    right = int(max(s[cv2.CC_STAT_LEFT] + s[cv2.CC_STAT_WIDTH] for s in kept))
    bottom = int(max(s[cv2.CC_STAT_TOP] + s[cv2.CC_STAT_HEIGHT] for s in kept))
    return (left, top, right, bottom)


def trim_image_margins(image: Image.Image) -> tuple[Image.Image, TrimResult]:
    """画像から白／黒の余白帯を除去した画像と、その結果情報を返す。

    安全弁のいずれかに該当した場合はトリミングを行わず、**入力画像オブジェクトを
    そのまま**返す。呼び出し側は ``result is image`` または ``TrimResult["trimmed"]``
    で判別できる。検出処理の例外は握りつぶさずログに記録したうえで、
    ``reason="error"`` として処理を継続する。

    Args:
        image: 処理対象の PIL 画像。

    Returns:
        (トリミング後の画像, :class:`TrimResult`) のタプル。
    """
    width, height = image.size
    full_bbox = (0, 0, width, height)

    try:
        bbox = detect_content_bbox(image)
    except Exception as exc:
        logger.error(
            "余白検出中にエラーが発生しました。トリミングをスキップします — %s",
            exc,
            exc_info=True,
        )
        return image, TrimResult(
            trimmed=False, bbox=full_bbox, keep_ratio=1.0, reason="error"
        )

    if bbox is None:
        return image, TrimResult(
            trimmed=False, bbox=full_bbox, keep_ratio=1.0, reason="no_content"
        )

    if bbox == full_bbox:
        logger.debug("余白は検出されませんでした (%dx%d)", width, height)
        return image, TrimResult(
            trimmed=False, bbox=full_bbox, keep_ratio=1.0, reason="no_margin"
        )

    left, top, right, bottom = bbox
    output_width = right - left
    output_height = bottom - top

    if output_width < MIN_OUTPUT_SIZE or output_height < MIN_OUTPUT_SIZE:
        logger.warning(
            "トリミング結果が小さすぎます (%dx%d)。トリミングをスキップします",
            output_width,
            output_height,
        )
        return image, TrimResult(
            trimmed=False, bbox=full_bbox, keep_ratio=1.0, reason="too_small"
        )

    keep_ratio = (output_width * output_height) / float(width * height)
    if keep_ratio < MIN_KEEP_AREA_RATIO:
        logger.warning(
            "トリミング残率が低すぎます (%.1f%%)。トリミングをスキップします",
            keep_ratio * 100,
        )
        return image, TrimResult(
            trimmed=False, bbox=full_bbox, keep_ratio=1.0, reason="too_aggressive"
        )

    logger.debug(
        "余白をトリミングしました: %dx%d → %dx%d (残率 %.0f%%)",
        width,
        height,
        output_width,
        output_height,
        keep_ratio * 100,
    )
    return image.crop(bbox), TrimResult(
        trimmed=True, bbox=bbox, keep_ratio=keep_ratio, reason="trimmed"
    )
