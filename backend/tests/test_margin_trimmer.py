"""margin_trimmer モジュールの単体テスト。

テスト対象:
    - detect_content_bbox: 白枠 / 黒枠 / 白黒混在 / 小さな UI 部品の無視 / 2 ページ並び
    - trim_image_margins: 安全弁（no_margin / no_content / too_small / too_aggressive / error）
"""

import pytest
from PIL import Image, ImageDraw

from margin_trimmer import (
    MIN_OUTPUT_SIZE,
    detect_content_bbox,
    trim_image_margins,
)


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _canvas(size: tuple[int, int], background: tuple[int, int, int]) -> Image.Image:
    """指定サイズ・単色背景の RGB 画像を作成する。

    Args:
        size: (width, height)。
        background: 背景色 RGB。

    Returns:
        作成した PIL 画像。
    """
    return Image.new("RGB", size, background)


def _fill(image: Image.Image, box: tuple[int, int, int, int],
          color: tuple[int, int, int]) -> None:
    """画像に矩形を描画する。

    Args:
        image: 描画対象の画像。
        box: (left, top, right, bottom)。right/bottom は exclusive として扱い、
            内部で ImageDraw の inclusive 座標へ変換する。
        color: 塗りつぶし色 RGB。
    """
    left, top, right, bottom = box
    ImageDraw.Draw(image).rectangle((left, top, right - 1, bottom - 1), fill=color)


WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (128, 128, 128)
CONTENT = (120, 60, 60)
CONTENT2 = (60, 60, 120)


# ---------------------------------------------------------------------------
# detect_content_bbox
# ---------------------------------------------------------------------------

class TestDetectContentBbox:
    """detect_content_bbox のテストクラス。"""

    def test_white_border_is_detected(self) -> None:
        """白背景の中央にあるカラー矩形の bbox が正確に求まること。"""
        image = _canvas((400, 400), WHITE)
        _fill(image, (100, 80, 300, 320), CONTENT)

        assert detect_content_bbox(image) == (100, 80, 300, 320)

    def test_black_border_is_detected(self) -> None:
        """黒背景でも同じ bbox が求まること。"""
        image = _canvas((400, 400), BLACK)
        _fill(image, (100, 80, 300, 320), CONTENT)

        assert detect_content_bbox(image) == (100, 80, 300, 320)

    def test_mixed_white_and_black_bands(self) -> None:
        """上下が黒帯・左右が白帯の画像で 4 辺すべてが除去されること。"""
        image = _canvas((400, 400), WHITE)
        _fill(image, (0, 0, 400, 50), BLACK)
        _fill(image, (0, 350, 400, 400), BLACK)
        _fill(image, (50, 50, 350, 350), CONTENT)

        assert detect_content_bbox(image) == (50, 50, 350, 350)

    def test_small_ui_element_is_ignored(self) -> None:
        """面積比 0.2% 未満の小さな要素が bbox に含まれないこと。

        1000x1000 の隅に置いた 20x20 の灰色矩形は面積比 0.04% であり、
        Kindle リーダーの UI ボタンを模している。
        """
        image = _canvas((1000, 1000), WHITE)
        _fill(image, (300, 300, 700, 700), CONTENT)
        _fill(image, (10, 10, 30, 30), GRAY)

        assert detect_content_bbox(image) == (300, 300, 700, 700)

    def test_two_pages_produce_union_bbox(self) -> None:
        """白ガターで隔てた 2 枚のページが両方含まれる外接矩形になること。

        最大成分だけを採る実装ではここで片方のページが失われる。
        """
        image = _canvas((1000, 500), WHITE)
        _fill(image, (100, 50, 400, 450), CONTENT)
        _fill(image, (600, 50, 900, 450), CONTENT2)

        assert detect_content_bbox(image) == (100, 50, 900, 450)

    def test_all_white_returns_none(self) -> None:
        """全面が純白の画像では有効な成分がなく None を返すこと。"""
        assert detect_content_bbox(_canvas((200, 200), WHITE)) is None

    def test_all_black_returns_none(self) -> None:
        """全面が純黒の画像でも None を返すこと。"""
        assert detect_content_bbox(_canvas((200, 200), BLACK)) is None

    def test_no_margin_returns_full_bbox(self) -> None:
        """余白のない画像では画像全体の bbox を返すこと。"""
        assert detect_content_bbox(_canvas((200, 200), GRAY)) == (0, 0, 200, 200)


# ---------------------------------------------------------------------------
# trim_image_margins
# ---------------------------------------------------------------------------

class TestTrimImageMargins:
    """trim_image_margins のテストクラス。"""

    def test_trims_and_reports_keep_ratio(self) -> None:
        """余白がある画像を切り出し、trimmed=True と残率を返すこと。"""
        image = _canvas((400, 400), WHITE)
        _fill(image, (100, 80, 300, 320), CONTENT)

        trimmed, info = trim_image_margins(image)

        assert info["trimmed"] is True
        assert info["reason"] == "trimmed"
        assert info["bbox"] == (100, 80, 300, 320)
        assert trimmed.size == (200, 240)
        assert info["keep_ratio"] == pytest.approx(200 * 240 / (400 * 400))

    def test_no_margin_returns_same_object(self) -> None:
        """余白がない画像では入力オブジェクトをそのまま返すこと。"""
        image = _canvas((200, 200), GRAY)

        trimmed, info = trim_image_margins(image)

        assert trimmed is image
        assert info["trimmed"] is False
        assert info["reason"] == "no_margin"
        assert info["keep_ratio"] == 1.0

    def test_all_white_returns_same_object(self) -> None:
        """全面白の画像では no_content として不変で返すこと。"""
        image = _canvas((200, 200), WHITE)

        trimmed, info = trim_image_margins(image)

        assert trimmed is image
        assert info["trimmed"] is False
        assert info["reason"] == "no_content"

    def test_all_black_returns_same_object(self) -> None:
        """全面黒の画像でも no_content として不変で返すこと。"""
        image = _canvas((200, 200), BLACK)

        trimmed, info = trim_image_margins(image)

        assert trimmed is image
        assert info["reason"] == "no_content"

    def test_too_aggressive_is_rejected(self) -> None:
        """残率が 5% 未満になるトリミングは中止されること。

        1000x1000 の中央にある 200x200 は残率 4% であり、
        コンテンツがほぼ存在しない異常な入力とみなす。
        """
        image = _canvas((1000, 1000), WHITE)
        _fill(image, (400, 400, 600, 600), CONTENT)

        trimmed, info = trim_image_margins(image)

        assert trimmed is image
        assert info["trimmed"] is False
        assert info["reason"] == "too_aggressive"

    def test_too_small_is_rejected(self) -> None:
        """出力の幅が MIN_OUTPUT_SIZE 未満になるトリミングは中止されること。"""
        image = _canvas((1000, 1000), WHITE)
        _fill(image, (490, 300, 510, 700), CONTENT)

        trimmed, info = trim_image_margins(image)

        assert 510 - 490 < MIN_OUTPUT_SIZE
        assert trimmed is image
        assert info["reason"] == "too_small"

    def test_detection_error_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """検出処理が例外を送出しても不変で返し、処理を継続できること。"""
        import margin_trimmer

        def _raise(_image: Image.Image) -> None:
            raise ValueError("検出失敗をシミュレート")

        monkeypatch.setattr(margin_trimmer, "detect_content_bbox", _raise)

        image = _canvas((200, 200), WHITE)
        trimmed, info = trim_image_margins(image)

        assert trimmed is image
        assert info["trimmed"] is False
        assert info["reason"] == "error"

    def test_grayscale_image_is_accepted(self) -> None:
        """RGB 以外のモードの画像でも処理できること。"""
        image = _canvas((400, 400), WHITE)
        _fill(image, (100, 80, 300, 320), CONTENT)
        gray_image = image.convert("L")

        trimmed, info = trim_image_margins(gray_image)

        assert info["trimmed"] is True
        assert trimmed.size == (200, 240)
