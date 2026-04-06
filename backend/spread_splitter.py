"""見開き画像分割モジュール。

フォトブックなどの見開き（スプレッド）画像を検出し、中央のストライプ（綴じ目）を
除去したうえで左右の個別ページ画像に分割する。

主な処理フロー:
    1. 中央ストライプの検出（Strategy A: 白ストライプ / Strategy B: 輝度勾配境界）
    2. ストライプが検出された場合は除去して結合画像を生成
    3. 顔検出関数で顔数を確認し、2 枚以上あれば左右に分割
"""

import logging
from pathlib import Path
from typing import Any, Callable, TypedDict

import numpy as np
from PIL import Image, ImageOps

from pillow_heif import register_heif_opener

register_heif_opener()

logger = logging.getLogger(__name__)


class SpreadResult(TypedDict):
    """見開き処理結果の型定義。"""

    action: str           # "split" | "kept" | "no_stripe"
    face_count: int
    stripe_detected: bool
    images: list[Image.Image]
    suffixes: list[str]   # [""] or ["_L", "_R"]
    face_detection: Any   # 全体画像に対する顔検出結果（非分割時に再利用可能）


def detect_center_stripe(
    image: Image.Image,
    search_width: int = 50,
) -> tuple[int, int] | None:
    """画像中央付近のストライプ（綴じ目）領域を検出する。

    Strategy A（明確な白ストライプ）と Strategy B（輝度勾配境界）の 2 段階で
    検出を試みる。Strategy A が成功した場合は Strategy B を実行しない。

    Strategy A — 明確な白ストライプ（Kindle フォトブックなど）:
        1. 画像中央 ± search_width ピクセルの列を切り出す
        2. 各列の平均輝度（全行・全 RGB チャンネルの平均）を計算する
        3. 輝度 > 240 の連続列を探す
        4. 連続列の幅が 10px 以上であれば検出成功とし、絶対座標を返す

    Strategy B — 輝度勾配境界（一部フォトブック）:
        1. 中央領域の列ごとの輝度勾配（隣接列差分）を計算する
        2. 最大輝度降下点（gradient < -30）を探す
        3. 降下点から左方向にさかのぼり、列平均輝度が 200 未満になる位置を
           グラデーション領域の開始点とする
        4. グラデーション領域の幅が 5px 以上であれば検出成功とし、絶対座標を返す

    Args:
        image: 処理対象の PIL 画像（RGB を想定）。
        search_width: 中央から左右に何ピクセル検索するか（デフォルト 50）。

    Returns:
        ストライプが検出された場合は絶対 x 座標の (stripe_start, stripe_end)、
        検出できない場合は None。
    """
    image_width, image_height = image.size
    center_x = image_width // 2

    left_bound = max(0, center_x - search_width)
    right_bound = min(image_width, center_x + search_width)

    if right_bound <= left_bound:
        logger.debug("検索領域が無効です (left=%d, right=%d)", left_bound, right_bound)
        return None

    # 中央検索領域を numpy 配列に変換して列ごとの平均輝度を計算する
    rgb_image = image.convert("RGB")
    region = rgb_image.crop((left_bound, 0, right_bound, image_height))
    region_array = np.array(region, dtype=np.float32)  # shape: (H, W_region, 3)

    # 各列の平均輝度: 全行・全チャンネルの平均
    col_means = region_array.mean(axis=(0, 2))  # shape: (W_region,)

    # ---- Strategy A: 明確な白ストライプ ----------------------------------------
    bright_cols = col_means > 240.0
    run_start: int | None = None
    best_run: tuple[int, int] | None = None  # (local_start, local_end) exclusive

    for local_x, is_bright in enumerate(bright_cols):
        if is_bright:
            if run_start is None:
                run_start = local_x
        else:
            if run_start is not None:
                run_len = local_x - run_start
                if run_len >= 10:
                    if best_run is None or run_len > (best_run[1] - best_run[0]):
                        best_run = (run_start, local_x)
                run_start = None

    # ループ終了後に開いているランを処理する
    if run_start is not None:
        run_len = len(col_means) - run_start
        if run_len >= 10:
            if best_run is None or run_len > (best_run[1] - best_run[0]):
                best_run = (run_start, len(col_means))

    if best_run is not None:
        abs_start = left_bound + best_run[0]
        abs_end = left_bound + best_run[1]
        logger.debug(
            "Strategy A でストライプを検出 — x=[%d, %d)", abs_start, abs_end
        )
        return (abs_start, abs_end)

    # ---- Strategy B: 輝度勾配境界 -----------------------------------------------
    if len(col_means) < 2:
        return None

    gradients = np.diff(col_means)  # shape: (W_region - 1,)

    drop_local = int(np.argmin(gradients))
    if gradients[drop_local] >= -30.0:
        logger.debug(
            "Strategy B: 有意な輝度降下が見つかりません (min_grad=%.2f)",
            float(gradients[drop_local]),
        )
        return None

    # drop_local は gradient の index; 対応する「右側」列は drop_local + 1
    drop_point = drop_local + 1  # 降下が始まった列（局所座標）

    # 降下点より左方向にさかのぼってコンテンツレベル（< 200）を探す
    grad_start = drop_local
    while grad_start > 0 and col_means[grad_start] >= 200.0:
        grad_start -= 1

    gradient_width = drop_point - grad_start
    if gradient_width < 5:
        logger.debug(
            "Strategy B: グラデーション領域が狭すぎます (width=%d)", gradient_width
        )
        return None

    abs_start = left_bound + grad_start
    abs_end = left_bound + drop_point
    logger.debug(
        "Strategy B でストライプを検出 — x=[%d, %d)", abs_start, abs_end
    )
    return (abs_start, abs_end)


def remove_stripe(
    image: Image.Image,
    stripe_start: int,
    stripe_end: int,
) -> Image.Image:
    """画像からストライプ領域を除去し、左右を結合した画像を返す。

    Args:
        image: 処理対象の PIL 画像。
        stripe_start: ストライプ開始の絶対 x 座標。
        stripe_end: ストライプ終了の絶対 x 座標（この列は含まない）。

    Returns:
        ストライプを除去し左右を結合した新しい PIL 画像。
    """
    image_width, image_height = image.size

    left = image.crop((0, 0, stripe_start, image_height))
    right = image.crop((stripe_end, 0, image_width, image_height))

    left_width = stripe_start
    right_width = image_width - stripe_end
    new_width = left_width + right_width

    joined = Image.new(image.mode, (new_width, image_height))
    joined.paste(left, (0, 0))
    joined.paste(right, (left_width, 0))

    logger.debug(
        "ストライプを除去しました — stripe=[%d, %d), 結合後の幅=%d",
        stripe_start,
        stripe_end,
        new_width,
    )
    return joined


def split_at_center(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """画像を中央（幅 // 2）で左右に分割する。

    Args:
        image: 分割対象の PIL 画像。

    Returns:
        (left_image, right_image) のタプル。
    """
    image_width, image_height = image.size
    mid = image_width // 2

    left = image.crop((0, 0, mid, image_height))
    right = image.crop((mid, 0, image_width, image_height))

    logger.debug(
        "中央で分割しました — 元の幅=%d, 分割点=%d", image_width, mid
    )
    return left, right


def process_spread(
    image_path: Path,
    count_persons_fn: Callable[[np.ndarray], int],
) -> SpreadResult:
    """見開き画像を処理し、ストライプ除去・人物検出・分割を行う。

    処理フロー:
        1. EXIF 情報を考慮して画像を開き、RGB に変換する
        2. ``detect_center_stripe()`` で中央ストライプを検出する
        3. ストライプが検出された場合は ``remove_stripe()`` で除去する
        4. ``count_persons_fn`` で人物数を取得する
        5. 人物数 >= 2 の場合は ``split_at_center()`` で左右に分割して返す
        6. 人物数 < 2 の場合は working_image をそのまま返す

    Args:
        image_path: 処理対象の画像ファイルパス。
        count_persons_fn: 人物検出関数。シグネチャは
            ``(image_array) -> int`` であり、検出された人物数を返す。

    Returns:
        :class:`SpreadResult` 辞書:
            - action (str): "split" | "kept" | "no_stripe"
            - person_count (int): 検出された人物の数
            - stripe_detected (bool): ストライプが検出されたか
            - images (list[Image.Image]): 結果画像リスト（呼び出し元が管理）
            - suffixes (list[str]): [""] または ["_L", "_R"]
    """
    # 画像を開いて EXIF 回転を適用し RGB に変換する
    raw_image = Image.open(image_path)
    raw_image = ImageOps.exif_transpose(raw_image)
    original = raw_image.convert("RGB")

    logger.debug("画像を読み込みました: %s (%dx%d)", image_path, *original.size)

    # ストライプ検出
    stripe_info: tuple[int, int] | None = None
    try:
        stripe_info = detect_center_stripe(original)
    except Exception as exc:
        logger.error(
            "ストライプ検出中にエラーが発生しました。スキップします — %s: %s",
            image_path,
            exc,
            exc_info=True,
        )

    stripe_detected = stripe_info is not None

    if stripe_detected:
        assert stripe_info is not None  # 型チェッカー向け
        logger.info(
            "ストライプを検出しました: %s — x=[%d, %d)",
            image_path,
            stripe_info[0],
            stripe_info[1],
        )
        working_image = remove_stripe(original, stripe_info[0], stripe_info[1])
    else:
        logger.debug("ストライプは検出されませんでした: %s", image_path)
        working_image = original

    # numpy 配列に変換して人物検出を実行する
    # 全体検出と左右分割検出の両方を試み、より多い方を採用する
    image_array = np.array(working_image, dtype=np.uint8)

    person_count = count_persons_fn(image_array)

    logger.info(
        "人物検出結果: %s — 人物数=%d", image_path, person_count
    )

    # 人物数に応じて分割判定を行う
    if person_count >= 2:
        left_img, right_img = split_at_center(working_image)
        logger.info("見開きを左右に分割します: %s", image_path)
        return SpreadResult(
            action="split",
            face_count=person_count,
            stripe_detected=stripe_detected,
            images=[left_img, right_img],
            suffixes=["_L", "_R"],
            face_detection=None,
        )
    else:
        action = "kept" if stripe_detected else "no_stripe"
        logger.info(
            "分割なし（%s）: %s — 人物数=%d", action, image_path, person_count
        )
        return SpreadResult(
            action=action,
            face_count=person_count,
            stripe_detected=stripe_detected,
            images=[working_image],
            suffixes=[""],
            face_detection=None,
        )
