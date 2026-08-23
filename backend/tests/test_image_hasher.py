"""image_hasher モジュールの単体テスト。

テスト対象:
    - compute_dhash: ハッシュ長 / 同一画像 / 再圧縮 / 別画像 / グレースケール入力
    - hamming_distance: 距離計算
    - DuplicateIndex: 閾値 0 / 閾値ありの検出、最近傍の選択、閾値の丸め
"""

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from image_hasher import (
    DEFAULT_MAX_DISTANCE,
    HASH_BITS,
    MAX_ALLOWED_DISTANCE,
    DuplicateIndex,
    compute_dhash,
    hamming_distance,
)


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _gradient_image(seed: int, size: tuple[int, int] = (240, 320)) -> Image.Image:
    """seed ごとに異なる、滑らかな模様を持つ RGB 画像を作る。

    単色や乱数では dHash が退化する（隣接画素の大小関係が定まらない、あるいは
    すべてランダムになる）ため、緩やかな勾配とブロック模様を重ねた画像を使う。

    Args:
        seed: 模様を決める整数。値が違えば見た目も明確に違う。
        size: (width, height)。

    Returns:
        生成した RGB 画像。
    """
    width, height = size
    ys, xs = np.mgrid[0:height, 0:width]
    base = (xs * (seed + 1) // 7 + ys * (seed + 3) // 5) % 256
    block = ((xs // (8 + seed)) + (ys // (6 + seed))) % 2 * 60
    arr = np.clip(base + block, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([arr, arr, arr]), mode="RGB")


def _recompress(image: Image.Image, quality: int = 95) -> Image.Image:
    """画像を JPEG で保存し直して読み戻す（再圧縮を再現する）。

    Args:
        image: 元画像。
        quality: JPEG 品質。

    Returns:
        再圧縮後の画像。
    """
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


# ---------------------------------------------------------------------------
# compute_dhash / hamming_distance
# ---------------------------------------------------------------------------

class TestComputeDhash:
    """compute_dhash のテストクラス。"""

    def test_hash_length_is_hash_bits(self) -> None:
        """ハッシュの要素数が HASH_BITS (256) であること。"""
        assert compute_dhash(_gradient_image(1)).shape == (HASH_BITS,)

    def test_identical_images_have_distance_zero(self) -> None:
        """同じ画像のハッシュは完全に一致すること。"""
        image = _gradient_image(1)

        assert hamming_distance(compute_dhash(image), compute_dhash(image.copy())) == 0

    def test_recompressed_image_stays_close(self) -> None:
        """JPEG 再圧縮しても距離がごく小さいこと。

        バイト列は変わるが見た目は同じ、という実データで最も多いケースを模す。
        """
        image = _gradient_image(2)

        distance = hamming_distance(
            compute_dhash(image), compute_dhash(_recompress(image))
        )

        assert distance <= 2

    def test_different_images_are_far_apart(self) -> None:
        """明確に別の画像は距離が大きいこと。"""
        distance = hamming_distance(
            compute_dhash(_gradient_image(1)), compute_dhash(_gradient_image(9))
        )

        assert distance >= 30

    def test_grayscale_input_matches_rgb(self) -> None:
        """グレースケール画像でも例外なく処理でき、RGB 版と同じ結果になること。"""
        image = _gradient_image(3)

        rgb_hash = compute_dhash(image)
        gray_hash = compute_dhash(image.convert("L"))

        assert hamming_distance(rgb_hash, gray_hash) == 0


class TestHammingDistance:
    """hamming_distance のテストクラス。"""

    def test_counts_differing_bits(self) -> None:
        """異なるビット数を数えること。"""
        a = np.array([True, False, True, False])
        b = np.array([True, True, False, False])

        assert hamming_distance(a, b) == 2


# ---------------------------------------------------------------------------
# DuplicateIndex
# ---------------------------------------------------------------------------

class TestDuplicateIndex:
    """DuplicateIndex のテストクラス。"""

    def test_empty_index_finds_nothing(self) -> None:
        """空のインデックスでは None が返ること。"""
        index = DuplicateIndex()

        assert index.find(compute_dhash(_gradient_image(1))) is None
        assert len(index) == 0

    def test_detects_identical_image_at_default_threshold(self) -> None:
        """既定の閾値 0 で、同一画像が重複として検出されること。"""
        index = DuplicateIndex()
        image_hash = compute_dhash(_gradient_image(1))
        index.add(image_hash, Path("first.jpg"))

        found = index.find(compute_dhash(_gradient_image(1)))

        assert found == (Path("first.jpg"), 0)
        assert len(index) == 1

    def test_does_not_detect_different_image(self) -> None:
        """別の画像は重複と判定されないこと。"""
        index = DuplicateIndex()
        index.add(compute_dhash(_gradient_image(1)), Path("first.jpg"))

        assert index.find(compute_dhash(_gradient_image(9))) is None

    def test_threshold_zero_rejects_small_distance(self) -> None:
        """閾値 0 では距離 1 以上のものを検出しないこと。"""
        index = DuplicateIndex(max_distance=0)
        base = compute_dhash(_gradient_image(1))
        index.add(base, Path("first.jpg"))

        near = base.copy()
        near[0] = not near[0]

        assert index.find(near) is None

    def test_raised_threshold_detects_near_match(self) -> None:
        """閾値を上げると近いものが検出されること。"""
        index = DuplicateIndex(max_distance=4)
        base = compute_dhash(_gradient_image(1))
        index.add(base, Path("first.jpg"))

        near = base.copy()
        near[0] = not near[0]
        near[1] = not near[1]

        assert index.find(near) == (Path("first.jpg"), 2)

    def test_returns_nearest_entry(self) -> None:
        """複数該当する場合、最も距離の近いものが返ること。"""
        index = DuplicateIndex(max_distance=8)
        base = compute_dhash(_gradient_image(1))

        far = base.copy()
        for i in range(3):
            far[i] = not far[i]
        near = base.copy()
        near[10] = not near[10]

        index.add(far, Path("far.jpg"))
        index.add(near, Path("near.jpg"))

        assert index.find(base) == (Path("near.jpg"), 1)

    def test_clamps_out_of_range_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """範囲外の閾値は丸められ、警告が出ること。"""
        index = DuplicateIndex(max_distance=999)

        assert index.max_distance == MAX_ALLOWED_DISTANCE
        assert any("丸めます" in record.message for record in caplog.records)

    def test_clamps_negative_threshold(self) -> None:
        """負の閾値は 0 に丸められること。"""
        assert DuplicateIndex(max_distance=-5).max_distance == 0

    def test_default_threshold_is_zero(self) -> None:
        """既定の閾値が DEFAULT_MAX_DISTANCE であること。"""
        assert DuplicateIndex().max_distance == DEFAULT_MAX_DISTANCE

    def test_grows_beyond_initial_capacity(self) -> None:
        """初期容量を超えて追加しても正しく検出できること。

        内部配列を倍々に伸ばす実装のため、伸長をまたいだ検索を確認する。
        """
        index = DuplicateIndex()
        hashes = [compute_dhash(_gradient_image(i)) for i in range(1, 40)]
        for i, h in enumerate(hashes):
            index.add(h, Path(f"{i}.jpg"))

        assert len(index) == 39
        assert index.find(hashes[0]) == (Path("0.jpg"), 0)
        assert index.find(hashes[-1]) == (Path("38.jpg"), 0)
