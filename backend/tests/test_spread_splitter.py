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
    crop_side_masks,
    detect_center_stripe,
    detect_side_masks,
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

    def test_process_spread_landscape_one_person_kept(self, tmp_path: Path) -> None:
        """横長でも人数 1 なら分割されず action="kept" が返ること。"""
        image_path = self._make_spread_image_file(tmp_path, with_stripe=False)
        count_fn = _make_count_persons_fn(person_count=1)

        result: SpreadResult = process_spread(image_path, count_fn)

        assert result["action"] == "kept", (
            f"action が 'kept' のはず: {result['action']}"
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

    def _make_masked_spread_file(
        self,
        tmp_path: Path,
        *,
        with_stripe: bool,
        filename: str = "masked.jpg",
    ) -> Path:
        """左右に黒帯を持つテスト用見開き画像を作成して返す。

        1000x400。左右各 100px を黒帯、中央 [100, 900) にコンテンツ。
        with_stripe=True の場合はコンテンツ中央 (x=490-509) に白ストライプを描画する。
        """
        width, height = 1000, 400
        img = Image.new("RGB", (width, height), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(100, 0), (899, height - 1)], fill=(0, 0, 200))
        if with_stripe:
            draw.rectangle([(490, 0), (509, height - 1)], fill=(255, 255, 255))
        path = tmp_path / filename
        img.save(path)
        return path

    def test_no_split_when_stripe_but_one_person(self, tmp_path: Path) -> None:
        """綴じ目ありでも人数 1 なら分割しないこと（AND 条件）。"""
        image_path = self._make_spread_image_file(tmp_path, with_stripe=True)
        count_fn = _make_count_persons_fn(person_count=1)

        result = process_spread(image_path, count_fn)

        assert result["action"] == "kept", f"action が 'kept' のはず: {result['action']}"
        assert result["suffixes"] == [""]

    def test_split_landscape_two_persons_no_stripe(self, tmp_path: Path) -> None:
        """横長 + 2人なら綴じ目がなくても分割すること（分割漏れの修正）。"""
        image_path = self._make_spread_image_file(tmp_path, with_stripe=False)
        count_fn = _make_count_persons_fn(person_count=2)

        result = process_spread(image_path, count_fn)

        assert result["action"] == "split", f"action が 'split' のはず: {result['action']}"
        assert len(result["images"]) == 2, "分割されるので画像は 2 枚"
        assert result["suffixes"] == ["_L", "_R"]

    def _make_portrait_image_file(
        self,
        tmp_path: Path,
        *,
        filename: str = "portrait.jpg",
    ) -> Path:
        """縦長（単ページ相当）のテスト用画像を作成して返す。

        400x800（アスペクト比 0.5 の縦長）。黒マスクなし。
        """
        img = Image.new("RGB", (400, 800), color=(0, 0, 200))
        path = tmp_path / filename
        img.save(path)
        return path

    def test_no_split_portrait_even_with_two_persons(self, tmp_path: Path) -> None:
        """縦長画像は人数 2 でも分割しないこと（中央被写体の見切れ防止）。"""
        image_path = self._make_portrait_image_file(tmp_path)
        count_fn = _make_count_persons_fn(person_count=2)

        result = process_spread(image_path, count_fn)

        assert result["action"] == "kept", f"action が 'kept' のはず: {result['action']}"
        assert len(result["images"]) == 1, "縦長は分割されないので画像は 1 枚"
        assert result["suffixes"] == [""]

    def test_masked_becomes_portrait_not_split(self, tmp_path: Path) -> None:
        """黒帯除去後に縦長になる画像は人数 2 でも分割しないこと（問題2の実ケース相当）。"""
        # 2000x800。左右に大きな黒帯、中央 [700, 1300) の 600px のみコンテンツ。
        # 黒帯除去後は 600x800（縦長）になる。
        img = Image.new("RGB", (2000, 800), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(700, 0), (1299, 799)], fill=(0, 0, 200))
        image_path = tmp_path / "masked_portrait.jpg"
        img.save(image_path)
        count_fn = _make_count_persons_fn(person_count=2)

        result = process_spread(image_path, count_fn)

        assert result["action"] == "kept", f"action が 'kept' のはず: {result['action']}"
        assert len(result["images"]) == 1
        # 黒帯除去で縦長（幅 < 高さ）になっていること
        assert result["images"][0].width < result["images"][0].height, "縦長にトリミングされているはず"

    def test_masked_spread_split_removes_black_bars(self, tmp_path: Path) -> None:
        """黒帯+綴じ目+2人 → 分割され、左右画像に黒帯が残らないこと（問題1の修正）。"""
        image_path = self._make_masked_spread_file(tmp_path, with_stripe=True)
        count_fn = _make_count_persons_fn(person_count=2)

        result = process_spread(image_path, count_fn)

        assert result["action"] == "split", f"action が 'split' のはず: {result['action']}"
        assert len(result["images"]) == 2
        # 左画像の左端列・右画像の右端列が黒でない（黒帯が除去されている）ことを確認
        left_img, right_img = result["images"]
        left_edge = np.asarray(left_img)[:, 0, :].mean()
        right_edge = np.asarray(right_img)[:, -1, :].mean()
        assert left_edge > 30, f"左画像の左端に黒帯が残っている: {left_edge}"
        assert right_edge > 30, f"右画像の右端に黒帯が残っている: {right_edge}"

    def test_masked_single_page_trimmed_not_split(self, tmp_path: Path) -> None:
        """黒帯+1人（横長）→ 人数不足で分割されずトリミングのみ。"""
        image_path = self._make_masked_spread_file(tmp_path, with_stripe=False)
        count_fn = _make_count_persons_fn(person_count=1)

        result = process_spread(image_path, count_fn)

        assert result["action"] == "kept", f"action が 'kept' のはず: {result['action']}"
        assert len(result["images"]) == 1
        # トリミングで幅が元の 1000 より小さくなっている（黒帯 200px 除去 → 約 800）
        assert result["images"][0].width < 1000, "黒帯がトリミングされていない"
        # 左右端が黒でない
        arr = np.asarray(result["images"][0])
        assert arr[:, 0, :].mean() > 30, "左端に黒帯が残っている"
        assert arr[:, -1, :].mean() > 30, "右端に黒帯が残っている"


# ---------------------------------------------------------------------------
# detect_side_masks
# ---------------------------------------------------------------------------


class TestDetectSideMasks:
    """detect_side_masks のテストクラス。"""

    def test_both_side_black_bars(self) -> None:
        """左右に黒帯、中央にグレー矩形の画像で境界が正しく返ること。"""
        width, height = 1000, 400
        img = Image.new("RGB", (width, height), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 中央 [200, 800) にグレーのコンテンツ
        draw.rectangle([(200, 0), (799, height - 1)], fill=(128, 128, 128))

        content_left, content_right = detect_side_masks(img)

        assert content_left == 200, f"左境界は 200 のはず: {content_left}"
        assert content_right == 800, f"右境界は 800 のはず: {content_right}"

    def test_no_black_bars(self) -> None:
        """黒帯のない画像では (0, width) が返ること。"""
        width, height = 800, 400
        img = Image.new("RGB", (width, height), color=(120, 120, 120))

        assert detect_side_masks(img) == (0, width)

    def test_safety_valve_all_dark(self) -> None:
        """ほぼ真っ黒な画像では MAX_MASK_RATIO を超えてトリミングしないこと。"""
        width, height = 1000, 400
        img = Image.new("RGB", (width, height), color=(0, 0, 0))

        content_left, content_right = detect_side_masks(img)

        # 片側の除去は 40% (=400px) 上限。左は最大 400、右境界は最小 600。
        assert content_left <= 400, f"左除去が上限超過: {content_left}"
        assert content_right >= 600, f"右除去が上限超過: {content_right}"

    def test_bright_subject_opposite_side(self) -> None:
        """黒帯の反対側に明るい矩形があっても黒帯だけ検出されること。"""
        width, height = 1000, 400
        img = Image.new("RGB", (width, height), color=(128, 128, 128))
        draw = ImageDraw.Draw(img)
        # 左端 [0, 150) に黒帯
        draw.rectangle([(0, 0), (149, height - 1)], fill=(0, 0, 0))
        # 右下に白い被写体（黒帯検出に影響しないこと）
        draw.rectangle([(850, 200), (999, height - 1)], fill=(255, 255, 255))

        content_left, content_right = detect_side_masks(img)

        assert content_left == 150, f"左境界は 150 のはず: {content_left}"
        assert content_right == width, f"右境界は width のはず: {content_right}"

    def test_narrow_bar_ignored(self) -> None:
        """MIN_MASK_WIDTH 未満の細い黒帯は無視されること。"""
        width, height = 800, 400
        img = Image.new("RGB", (width, height), color=(120, 120, 120))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (2, height - 1)], fill=(0, 0, 0))  # 幅 3px

        content_left, content_right = detect_side_masks(img)

        assert content_left == 0, f"細い帯は無視され 0 のはず: {content_left}"
        assert content_right == width


# ---------------------------------------------------------------------------
# crop_side_masks
# ---------------------------------------------------------------------------


class TestCropSideMasks:
    """crop_side_masks のテストクラス。"""

    def test_crops_to_content_region(self) -> None:
        """指定した content 範囲でトリミングされること。"""
        width, height = 1000, 400
        img = Image.new("RGB", (width, height), color=(50, 60, 70))

        cropped = crop_side_masks(img, 200, 800)

        assert cropped.size == (600, height), f"サイズが (600, {height}) のはず: {cropped.size}"

    def test_returns_original_when_full_range(self) -> None:
        """(0, width) のときは元画像オブジェクトをそのまま返すこと。"""
        width, height = 800, 400
        img = Image.new("RGB", (width, height), color=(50, 60, 70))

        result = crop_side_masks(img, 0, width)

        assert result is img, "トリミング不要時は同一オブジェクトを返すはず"


# ---------------------------------------------------------------------------
# process_spread の余白トリミング統合
# ---------------------------------------------------------------------------

class TestProcessSpreadTrimMargins:
    """process_spread の trim_margins 引数のテストクラス。"""

    def test_trim_margins_disabled_keeps_white_margin(self, tmp_path: Path) -> None:
        """trim_margins=False では白余白がそのまま残ること（既存動作の保持）。"""
        width, height = 800, 600
        img = Image.new("RGB", (width, height), color=(255, 255, 255))
        ImageDraw.Draw(img).rectangle((200, 100, 599, 499), fill=(120, 60, 60))
        image_path = tmp_path / "margin.png"
        img.save(image_path)

        result = process_spread(image_path, _make_count_persons_fn(1))

        assert result["action"] == "kept"
        assert result["images"][0].size == (width, height)

    def test_trim_margins_removes_white_border(self, tmp_path: Path) -> None:
        """trim_margins=True で読み込み直後の白余白が除去されること。

        800x600 の白背景に 400x400 のコンテンツを置く。トリミング後は縦横比 1.0 で
        人物数 1 のため分割されず、コンテンツ矩形そのものが返る。
        """
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        ImageDraw.Draw(img).rectangle((200, 100, 599, 499), fill=(120, 60, 60))
        image_path = tmp_path / "margin.png"
        img.save(image_path)

        result = process_spread(
            image_path, _make_count_persons_fn(1), trim_margins=True
        )

        assert result["action"] == "kept"
        assert result["images"][0].size == (400, 400)

    def test_trim_margins_applies_after_split(self, tmp_path: Path) -> None:
        """分割後の各画像に残った余白も除去されること。

        1200x400 の白背景に 300x300 のページを 2 枚（左右）配置する。
        1 回目のトリミングで外周が落ちて 800x300 になり、横長かつ人物数 2 のため
        中央で 400x300 ずつに分割される。分割後の各画像には内側のガター由来の
        白帯 100px が残るため、2 回目のトリミングで 300x300 になる。
        """
        img = Image.new("RGB", (1200, 400), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((200, 50, 499, 349), fill=(120, 60, 60))
        draw.rectangle((700, 50, 999, 349), fill=(60, 60, 120))
        image_path = tmp_path / "spread.png"
        img.save(image_path)

        result = process_spread(
            image_path, _make_count_persons_fn(2), trim_margins=True
        )

        assert result["action"] == "split"
        assert [img.size for img in result["images"]] == [(300, 300), (300, 300)]
