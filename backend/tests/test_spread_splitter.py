"""spread_splitter モジュールの単体テスト。

テスト対象:
    - detect_center_stripe: Strategy A（白ストライプ）/ Strategy B（輝度勾配）/ 検出なし
    - remove_stripe: ストライプ除去と左右結合
    - split_at_center: 中央分割
    - process_spread: 統合処理（人物検出関数はモック）
"""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image, ImageDraw

from spread_splitter import (
    SpreadResult,
    detect_center_stripe,
    process_spread,
    remove_stripe,
    split_at_center,
)


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _make_count_persons_fn(person_count: int) -> MagicMock:
    """指定した person_count を返す人物検出モック関数を作成する。

    Args:
        person_count: モックが返す人物数。

    Returns:
        int を返す MagicMock。
    """
    return MagicMock(return_value=person_count)


# ---------------------------------------------------------------------------
# detect_center_stripe
# ---------------------------------------------------------------------------

class TestDetectCenterStripe:
    """detect_center_stripe のテストクラス。"""

    def test_detect_center_stripe_white_stripe(self) -> None:
        """Strategy A: 中央に 20px の白ストライプがある画像で検出できること。

        800x400 画像の左側を青、右側を青で塗り、x=390〜410 に白ストライプを描画する。
        戻り値がおよそ (390, 410) であることを確認する。
        """
        width, height = 800, 400
        img = Image.new("RGB", (width, height), color=(0, 0, 200))
        draw = ImageDraw.Draw(img)
        stripe_start = 390
        stripe_end = 410  # exclusive → 幅 20px
        draw.rectangle([(stripe_start, 0), (stripe_end - 1, height - 1)], fill=(255, 255, 255))

        result = detect_center_stripe(img, search_width=50)

        assert result is not None, "白ストライプが検出されるべき"
        detected_start, detected_end = result
        # ストライプ位置がおおよそ ±5px の範囲に収まることを確認する
        assert abs(detected_start - stripe_start) <= 5, (
            f"stripe_start の誤差が大きすぎます: expected ~{stripe_start}, got {detected_start}"
        )
        assert abs(detected_end - stripe_end) <= 5, (
            f"stripe_end の誤差が大きすぎます: expected ~{stripe_end}, got {detected_end}"
        )

    def test_detect_center_stripe_gradient(self) -> None:
        """Strategy B: 中央で輝度が急落 (gradient < -30) する画像で検出できること。

        左半分を輝度 220 の明るいグレー、右半分を輝度 150 の暗いグレーとし、
        x=400 の 1 列境界で輝度差 70 の急落を作る。
        Strategy B が発動し、None 以外が返ることを確認する。

        背景:
            Strategy B は単一ステップで gradient < -30 となる最大降下点を探す。
            15px にわたる緩やかなグラデーション（1 ステップあたり -5）では
            閾値 -30 を超えないため、ここでは 1 列で -70 の急落を使用する。
        """
        width, height = 800, 400
        img = Image.new("RGB", (width, height))
        pixels = img.load()

        # 左半分 (x = 0..399): 輝度 220（コンテンツ領域、≥ 200）
        for x in range(0, 400):
            for y in range(height):
                pixels[x, y] = (220, 220, 220)  # type: ignore[index]

        # 右半分 (x = 400..799): 輝度 150（暗い領域、< 200）
        # x=400 の 1 列で輝度差 -70 の急落が発生し Strategy B の条件を満たす
        for x in range(400, width):
            for y in range(height):
                pixels[x, y] = (150, 150, 150)  # type: ignore[index]

        result = detect_center_stripe(img, search_width=50)

        assert result is not None, (
            "輝度の急落境界が検出されるべき (Strategy B)"
        )

    def test_detect_center_stripe_no_stripe(self) -> None:
        """均一なグレー画像ではストライプが検出されないこと。

        800x400 の均一グレー (128, 128, 128) 画像に対して None が返ることを確認する。
        """
        img = Image.new("RGB", (800, 400), color=(128, 128, 128))

        result = detect_center_stripe(img, search_width=50)

        assert result is None, "均一グレー画像ではストライプは検出されないべき"


# ---------------------------------------------------------------------------
# remove_stripe
# ---------------------------------------------------------------------------

class TestRemoveStripe:
    """remove_stripe のテストクラス。"""

    def test_remove_stripe(self) -> None:
        """ストライプ除去後の幅と左右の色が正しいこと。

        800x400 画像で左側を赤、中央 20px を白、右側を青に設定する。
        ストライプ (390, 410) を除去した結果が 780px 幅で、
        左半分が赤・右半分が青であることを確認する。
        """
        width, height = 800, 400
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)

        draw.rectangle([(0, 0), (389, height - 1)], fill=(255, 0, 0))      # 左: 赤
        draw.rectangle([(390, 0), (409, height - 1)], fill=(255, 255, 255))  # 中央: 白
        draw.rectangle([(410, 0), (width - 1, height - 1)], fill=(0, 0, 255))  # 右: 青

        result = remove_stripe(img, stripe_start=390, stripe_end=410)

        # 幅の検証: 800 - 20 = 780
        assert result.width == 780, f"期待幅 780, 実際 {result.width}"
        assert result.height == height, f"高さは変わらないべき: {result.height}"

        # 左半分のサンプリング: 赤 (255, 0, 0)
        left_pixel = result.getpixel((100, 200))
        assert left_pixel == (255, 0, 0), f"左半分は赤のはず: {left_pixel}"

        # 右半分のサンプリング: 青 (0, 0, 255)
        right_pixel = result.getpixel((500, 200))
        assert right_pixel == (0, 0, 255), f"右半分は青のはず: {right_pixel}"


# ---------------------------------------------------------------------------
# split_at_center
# ---------------------------------------------------------------------------

class TestSplitAtCenter:
    """split_at_center のテストクラス。"""

    def test_split_at_center(self) -> None:
        """800x400 画像を分割した結果がそれぞれ 400x400 であること。"""
        img = Image.new("RGB", (800, 400), color=(100, 150, 200))

        left, right = split_at_center(img)

        assert left.size == (400, 400), f"左画像サイズが期待値と異なります: {left.size}"
        assert right.size == (400, 400), f"右画像サイズが期待値と異なります: {right.size}"

    def test_split_at_center_content(self) -> None:
        """分割後の左右に元画像の対応する内容が含まれていること。"""
        img = Image.new("RGB", (800, 400))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (399, 399)], fill=(255, 0, 0))    # 左: 赤
        draw.rectangle([(400, 0), (799, 399)], fill=(0, 0, 255))  # 右: 青

        left, right = split_at_center(img)

        assert left.getpixel((100, 100)) == (255, 0, 0), "左画像は赤のはず"
        assert right.getpixel((100, 100)) == (0, 0, 255), "右画像は青のはず"


# ---------------------------------------------------------------------------
# process_spread
# ---------------------------------------------------------------------------

class TestProcessSpread:
    """process_spread の統合テストクラス（顔検出はモック）。"""

    def _make_spread_image_file(
        self,
        tmp_path: Path,
        *,
        with_stripe: bool,
        filename: str = "spread.jpg",
    ) -> Path:
        """テスト用の見開き画像ファイルを作成して返す。

        Args:
            tmp_path: pytest の tmp_path フィクスチャ。
            with_stripe: True の場合は中央に白ストライプを描画する。
            filename: 作成するファイル名。

        Returns:
            作成した画像ファイルのパス。
        """
        width, height = 800, 400
        img = Image.new("RGB", (width, height), color=(0, 0, 200))

        if with_stripe:
            draw = ImageDraw.Draw(img)
            draw.rectangle([(390, 0), (409, height - 1)], fill=(255, 255, 255))

        path = tmp_path / filename
        img.save(path)
        return path

    def test_process_spread_split_2_persons(self, tmp_path: Path) -> None:
        """人物数 2 のとき action="split"、2 枚の画像、suffixes=["_L", "_R"] が返ること。"""
        image_path = self._make_spread_image_file(tmp_path, with_stripe=True)
        count_fn = _make_count_persons_fn(person_count=2)

        result: SpreadResult = process_spread(image_path, count_fn)

        assert result["action"] == "split", f"action が 'split' のはず: {result['action']}"
        assert result["face_count"] == 2, f"face_count が 2 のはず: {result['face_count']}"
        assert result["stripe_detected"] is True, "ストライプが検出されるべき"
        assert len(result["images"]) == 2, f"画像が 2 枚のはず: {len(result['images'])}"
        assert result["suffixes"] == ["_L", "_R"], f"suffixes が ['_L', '_R'] のはず: {result['suffixes']}"

    def test_process_spread_kept_1_person(self, tmp_path: Path) -> None:
        """人物数 1 のとき action="kept"、1 枚の画像、suffixes=[""] が返ること。"""
        image_path = self._make_spread_image_file(tmp_path, with_stripe=True)
        count_fn = _make_count_persons_fn(person_count=1)

        result: SpreadResult = process_spread(image_path, count_fn)

        assert result["action"] == "kept", f"action が 'kept' のはず: {result['action']}"
        assert result["face_count"] == 1, f"face_count が 1 のはず: {result['face_count']}"
        assert result["stripe_detected"] is True, "ストライプが検出されるべき"
        assert len(result["images"]) == 1, f"画像が 1 枚のはず: {len(result['images'])}"
        assert result["suffixes"] == [""], f"suffixes が [''] のはず: {result['suffixes']}"

    def test_process_spread_no_stripe(self, tmp_path: Path) -> None:
        """ストライプなし画像では action="no_stripe" が返ること。"""
        image_path = self._make_spread_image_file(tmp_path, with_stripe=False)
        count_fn = _make_count_persons_fn(person_count=1)

        result: SpreadResult = process_spread(image_path, count_fn)

        assert result["action"] == "no_stripe", (
            f"action が 'no_stripe' のはず: {result['action']}"
        )
        assert result["stripe_detected"] is False, "ストライプは検出されないべき"
        assert len(result["images"]) == 1, f"画像が 1 枚のはず: {len(result['images'])}"
        assert result["suffixes"] == [""], f"suffixes が [''] のはず: {result['suffixes']}"

    def test_process_spread_calls_count_fn_with_array(
        self, tmp_path: Path
    ) -> None:
        """count_persons_fn が numpy 配列を引数として呼ばれること。"""
        image_path = self._make_spread_image_file(tmp_path, with_stripe=False)
        count_fn = _make_count_persons_fn(person_count=0)

        process_spread(image_path, count_fn)

        count_fn.assert_called_once()
        call_args = count_fn.call_args
        # 第 1 引数は numpy 配列
        assert isinstance(call_args[0][0], np.ndarray), "第 1 引数は numpy 配列のはず"
