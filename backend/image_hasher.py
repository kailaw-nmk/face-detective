"""知覚ハッシュによる重複画像検出モジュール。

同じ画像がフォルダ内に複数含まれる場合に、2 枚目以降を検出する。バイト単位の
一致ではなく見た目の一致で判定するため、JPEG の再圧縮などでバイト列が変わって
いても同一と判定できる。実データではバイト単位で完全一致する重複は稀で、
「見た目は同じだがバイト列は異なる」重複が大半だった。

アルゴリズムは dHash (difference hash):
    1. グレースケール化して (DHASH_SIZE + 1, DHASH_SIZE) に縮小する
    2. 横方向に隣接する画素を比較し、右のほうが明るければ True とする
    3. 得られた DHASH_SIZE * DHASH_SIZE ビットを指紋とする

ハッシュ長を 16x16 = 256bit にしているのは実測に基づく。64bit (8x8) では偶然の
一致が起きやすく、閾値を少しでも上げると誤検出が急増した。256bit では本物の
重複と別画像の間に広い空白が生まれる。
"""

import logging
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ハッシュのパラメータ
DHASH_SIZE = 16                      # 縮小後の一辺（px）
HASH_BITS = DHASH_SIZE * DHASH_SIZE  # ハッシュのビット数（256）

# 許容ハミング距離
DEFAULT_MAX_DISTANCE = 0   # 既定は完全一致のみ（実測で誤検出ゼロ）
MAX_ALLOWED_DISTANCE = 32  # 指定できる上限。これを超えると別画像を巻き込む

# DuplicateIndex の内部配列の初期容量。超えたら倍々に伸ばす
_INITIAL_CAPACITY = 256


def compute_dhash(image: Image.Image) -> np.ndarray:
    """画像の dHash を計算する。

    Args:
        image: 対象の PIL 画像。RGB 以外のモードでも受け付ける。

    Returns:
        要素数 ``HASH_BITS`` の bool 配列。numpy でベクトル化して距離を計算する
        ため、整数ではなく配列で返す。
    """
    gray = image.convert("L").resize((DHASH_SIZE + 1, DHASH_SIZE), Image.LANCZOS)
    arr = np.asarray(gray, dtype=np.int16)
    # 横方向の隣接画素を比較する（右のほうが明るければ True）
    return (arr[:, 1:] > arr[:, :-1]).flatten()


def hamming_distance(a: np.ndarray, b: np.ndarray) -> int:
    """2 つのハッシュのハミング距離（異なるビット数）を返す。

    Args:
        a: 比較元のハッシュ。
        b: 比較先のハッシュ。

    Returns:
        異なるビットの個数。
    """
    return int(np.count_nonzero(a != b))


class DuplicateIndex:
    """走査済み画像のハッシュを保持し、重複を判定する。

    ハッシュは 2 次元 bool 配列に積み、検索は numpy で全件との距離を一度に求める。
    配列は容量を倍々に伸ばして再利用する。追加のたびに積み直す実装だと、走査枚数が
    数千になったときに O(n^2) のメモリコピーになるため。
    """

    def __init__(self, max_distance: int = DEFAULT_MAX_DISTANCE) -> None:
        """インデックスを初期化する。

        Args:
            max_distance: 重複とみなす最大ハミング距離。範囲外の値は
                0 〜 ``MAX_ALLOWED_DISTANCE`` に丸め、警告ログを出す
                （不正値でジョブを止めないため）。
        """
        if max_distance < 0 or max_distance > MAX_ALLOWED_DISTANCE:
            clamped = max(0, min(max_distance, MAX_ALLOWED_DISTANCE))
            logger.warning(
                "許容ハミング距離が範囲外です (%d)。%d に丸めます",
                max_distance,
                clamped,
            )
            max_distance = clamped

        self.max_distance = max_distance
        self._stack = np.empty((_INITIAL_CAPACITY, HASH_BITS), dtype=bool)
        self._paths: list[Path] = []
        self._count = 0

    def __len__(self) -> int:
        """登録済みのハッシュ数を返す。"""
        return self._count

    def find(self, image_hash: np.ndarray) -> tuple[Path, int] | None:
        """許容距離以内で最も近い既出画像を探す。

        Args:
            image_hash: 検索するハッシュ。

        Returns:
            見つかった場合は (最初に登録されたパス, ハミング距離) のタプル。
            距離が同点の場合は先に登録されたほうを返す。該当がなければ None。
        """
        if self._count == 0:
            return None

        distances = np.count_nonzero(
            self._stack[: self._count] != image_hash, axis=1
        )
        nearest = int(np.argmin(distances))  # 同点なら最初の要素
        distance = int(distances[nearest])
        if distance <= self.max_distance:
            return self._paths[nearest], distance
        return None

    def add(self, image_hash: np.ndarray, path: Path) -> None:
        """ハッシュとそのパスを登録する。

        Args:
            image_hash: 登録するハッシュ。
            path: そのハッシュを持つ画像のパス。
        """
        if self._count == len(self._stack):
            grown = np.empty((len(self._stack) * 2, HASH_BITS), dtype=bool)
            grown[: self._count] = self._stack[: self._count]
            self._stack = grown

        self._stack[self._count] = image_hash
        self._paths.append(path)
        self._count += 1
