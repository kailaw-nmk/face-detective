# 余白トリミング機能 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 画像の四辺にある均一な白／黒の余白帯を検出して除去し、写真部分だけを顔検出・保存の対象にする。

**Architecture:** 新規モジュール `backend/margin_trimmer.py` が「1 枚の PIL 画像から余白を除いた矩形を求めて切り出す」という単一責務を持つ。OpenCV の連結成分解析で「白でも黒でもない画素」の塊を求め、面積比 0.2% 以上の全成分の外接矩形の和を取る。この関数を見開き分割経路（読み込み直後と分割後の 2 箇所）と通常経路に差し込み、UI の独立チェックボックスで ON/OFF する。

**Tech Stack:** Python 3.12 / FastAPI / Pillow / OpenCV (`cv2`) / NumPy / pytest / React + TypeScript + Tailwind CSS / Vite

**Spec:** `docs/superpowers/specs/2026-08-22-margin-trim-design.md`

## Global Constraints

- 作業ブランチは `feature/margin-trim`（作成済み）。
- Python は PEP 8 に従い `ruff` でリントする。関数には日本語 docstring を付ける。
- TypeScript の関数・コンポーネントには JSDoc を付ける。
- テストは `backend/` を作業ディレクトリとして実行する（`conftest.py` が `sys.path` を通す）: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest ...`
- 個別ファイルのエラーはログに記録して次に進む。ジョブ全体を止めない。
- 新規 API フィールド・関数引数はすべて **デフォルト値付き**にし、既存の呼び出し側とテストを壊さない。
- 公開関数名は `trim_image_margins`。`trim_margins` は bool 引数・API フィールドの名前として使うため、関数に同じ名前を使うと変数にシャドウされる。
- 定数の値（spec より、逐語）: `WHITE_THRESHOLD = 240.0` / `BLACK_THRESHOLD = 15.0` / `MIN_COMPONENT_AREA_RATIO = 0.002` / `OPEN_KERNEL_SIZE = 9` / `MIN_KEEP_AREA_RATIO = 0.05` / `MIN_OUTPUT_SIZE = 32`
- `reason` の値は `"trimmed"` / `"no_margin"` / `"no_content"` / `"too_aggressive"` / `"too_small"` / `"error"` の 6 種のみ。
- 安全弁の評価順は `no_content` → `no_margin` → `too_small` → `too_aggressive`。
- 安全弁に該当した場合は **入力画像オブジェクトをそのまま返す**（`result is image` が True になる）。
- WebSocket のメッセージ型は `progress` / `complete` / `error` の 3 種のまま増やさない。トリミングの記録は `logging` で `logs/` に出力する。
- `frontend/dist/` は `.gitignore` 対象で git 管理外。ビルド成果物はコミットしない。

---

### Task 1: `margin_trimmer` モジュール

**Files:**
- Create: `backend/margin_trimmer.py`
- Test: `backend/tests/test_margin_trimmer.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Consumes: なし（新規の葉モジュール）
- Produces:
  - `TrimResult` (TypedDict): `trimmed: bool`, `bbox: tuple[int, int, int, int]`, `keep_ratio: float`, `reason: str`
  - `detect_content_bbox(image: Image.Image) -> tuple[int, int, int, int] | None`
  - `trim_image_margins(image: Image.Image) -> tuple[Image.Image, TrimResult]`
  - 定数: `WHITE_THRESHOLD`, `BLACK_THRESHOLD`, `MIN_COMPONENT_AREA_RATIO`, `OPEN_KERNEL_SIZE`, `MIN_KEEP_AREA_RATIO`, `MIN_OUTPUT_SIZE`

- [ ] **Step 1: `requirements.txt` に `opencv-python` を追加**

`cv2` は現在 `mediapipe` と `ultralytics` の間接依存として venv に入っているが、このモジュールが直接 import するため明示する。`backend/requirements.txt` の `ultralytics` の次の行に追加する:

```
fastapi
uvicorn[standard]
websockets
mediapipe
ultralytics
opencv-python
Pillow
pillow-heif
ruff
pytest
httpx2
```

- [ ] **Step 2: 失敗するテストを書く**

`backend/tests/test_margin_trimmer.py` を新規作成する。すべての入力画像は Pillow で合成する（実サンプルはリポジトリにコミットしない）。ここに書いた bbox の期待値はすべて実測で検証済みなので、そのまま使うこと。

```python
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
```

- [ ] **Step 3: テストを実行して失敗を確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/test_margin_trimmer.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'margin_trimmer'`（コレクションエラー）

- [ ] **Step 4: `margin_trimmer.py` を実装する**

`backend/margin_trimmer.py` を新規作成する:

```python
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
    arr = np.asarray(rgb, dtype=np.float32)      # shape: (H, W, 3)
    luminance = arr.mean(axis=2)                  # shape: (H, W)
    height, width = luminance.shape

    margin_mask = (luminance > WHITE_THRESHOLD) | (luminance < BLACK_THRESHOLD)
    content_mask = (~margin_mask).astype(np.uint8)

    kernel = np.ones((OPEN_KERNEL_SIZE, OPEN_KERNEL_SIZE), np.uint8)
    content_mask = cv2.morphologyEx(content_mask, cv2.MORPH_OPEN, kernel)

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        content_mask, 8
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

    logger.info(
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
```

- [ ] **Step 5: テストを実行して成功を確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/test_margin_trimmer.py -v`

Expected: PASS（16 テストすべて）

- [ ] **Step 6: リントを実行する**

Run: `cd C:\AI\face-detective && venv\Scripts\python.exe -m ruff check backend/margin_trimmer.py backend/tests/test_margin_trimmer.py`

Expected: `All checks passed!`。指摘があれば修正して再実行する。

- [ ] **Step 7: コミット**

```bash
git add backend/margin_trimmer.py backend/tests/test_margin_trimmer.py backend/requirements.txt
git commit -m "feat: 白/黒余白を検出してトリミングする margin_trimmer を追加"
```

---

### Task 2: 見開き分割経路への統合

**Files:**
- Modify: `backend/spread_splitter.py`
- Test: `backend/tests/test_spread_splitter.py`

**Interfaces:**
- Consumes: `margin_trimmer.trim_image_margins(image) -> tuple[Image.Image, TrimResult]`（Task 1）
- Produces: `process_spread(image_path: Path, count_persons_fn: Callable[[np.ndarray], int], trim_margins: bool = False) -> SpreadResult`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_spread_splitter.py` の末尾に以下のクラスを追加する。ファイル先頭の import 群には `process_spread` が既にあるので変更不要。

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/test_spread_splitter.py::TestProcessSpreadTrimMargins -v`

Expected: FAIL — `test_trim_margins_removes_white_border` と `test_trim_margins_applies_after_split` が `TypeError: process_spread() got an unexpected keyword argument 'trim_margins'`。`test_trim_margins_disabled_keeps_white_margin` は既存動作なので PASS する。

- [ ] **Step 3: `spread_splitter.py` に import と補助関数を追加する**

既存の import ブロック（`from pillow_heif import register_heif_opener` の直前）に追加する:

```python
from margin_trimmer import trim_image_margins
```

`process_spread` の定義の直前に、分割後トリミング用の補助関数を追加する:

```python
def _trim_output_images(
    images: list[Image.Image],
    image_path: Path,
) -> list[Image.Image]:
    """分割後の各画像に残っている余白をトリミングする。

    中央で分割すると、綴じ目のガター由来の白帯が各画像の内側の端に残る。
    1 回目（読み込み直後）のトリミングでは外周しか落ちないため、ここで再度適用する。

    Args:
        images: トリミング対象の画像リスト。
        image_path: ログ出力用の元画像パス。

    Returns:
        トリミング後の画像リスト。順序は入力と同じ。
    """
    trimmed_images: list[Image.Image] = []
    for index, img in enumerate(images):
        trimmed, info = trim_image_margins(img)
        if info["trimmed"]:
            logger.info(
                "分割後の余白をトリミングしました (%d/%d): %s — %dx%d → %dx%d",
                index + 1,
                len(images),
                image_path,
                img.width,
                img.height,
                trimmed.width,
                trimmed.height,
            )
        trimmed_images.append(trimmed)
    return trimmed_images
```

- [ ] **Step 4: `process_spread` のシグネチャと docstring を更新する**

シグネチャを変更する:

```python
def process_spread(
    image_path: Path,
    count_persons_fn: Callable[[np.ndarray], int],
    trim_margins: bool = False,
) -> SpreadResult:
```

docstring の `Args:` に 1 行追加する:

```
        trim_margins: 白／黒の余白トリミングを有効にするかどうか。有効な場合、
            読み込み直後と分割後の 2 箇所で ``trim_image_margins()`` を適用する。
```

docstring の処理フロー説明のうち、手順 1 と 2 の間に新しい手順を挿し、以降の番号を繰り下げる:

```
        1. EXIF 情報を考慮して画像を開き、RGB に変換する
        2. ``trim_margins`` が有効なら ``trim_image_margins()`` で余白を除去する
        3. ``detect_side_masks()`` で左右の黒マスク（縦の黒帯）を検出し、
           ``crop_side_masks()`` でトリミングする（分割の有無に関わらず常に適用）
        4. ``detect_center_stripe()`` で中央ストライプを検出する
        5. ストライプが検出された場合は ``remove_stripe()`` で除去する
        6. ``count_persons_fn`` で人物数を取得する
        7. 黒マスク除去後が横長（アスペクト比 >= ``MIN_SPREAD_ASPECT``）かつ
           人物数 >= 2 の両方が成立した場合のみ ``split_at_center()`` で左右に分割して返す
        8. それ以外の場合はトリミング済み画像 1 枚をそのまま返す（単ページは縦長になり分割されない）
        9. ``trim_margins`` が有効なら、返す各画像に再度余白トリミングを適用する
```

- [ ] **Step 5: 1 回目のトリミングを差し込む**

`original = raw_image.convert("RGB")` と、その次の `logger.debug("画像を読み込みました: ...")` の**間**に挿入する:

```python
    if trim_margins:
        original, trim_info = trim_image_margins(original)
        if trim_info["trimmed"]:
            logger.info(
                "読み込み時に余白をトリミングしました: %s — 残率 %.0f%%",
                image_path,
                trim_info["keep_ratio"] * 100,
            )
```

- [ ] **Step 6: 2 回目のトリミングを差し込む**

`process_spread` の末尾にある 2 つの `return SpreadResult(...)` を書き換える。分割ブランチ:

```python
    if should_split:
        left_img, right_img = split_at_center(working_image)
        logger.info(
            "見開きを左右に分割します: %s — アスペクト比=%.2f, 人物数=%d",
            image_path, aspect_ratio, person_count,
        )
        output_images = [left_img, right_img]
        if trim_margins:
            output_images = _trim_output_images(output_images, image_path)
        return SpreadResult(
            action="split",
            face_count=person_count,
            stripe_detected=stripe_detected,
            images=output_images,
            suffixes=["_L", "_R"],
            face_detection=None,
        )
```

非分割ブランチ:

```python
    else:
        logger.info(
            "分割なし（kept）: %s — アスペクト比=%.2f, 人物数=%d, ストライプ=%s",
            image_path, aspect_ratio, person_count, stripe_detected,
        )
        output_images = [working_image]
        if trim_margins:
            output_images = _trim_output_images(output_images, image_path)
        return SpreadResult(
            action="kept",
            face_count=person_count,
            stripe_detected=stripe_detected,
            images=output_images,
            suffixes=[""],
            face_detection=None,
        )
```

- [ ] **Step 7: テスト全体を実行して成功を確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/test_spread_splitter.py tests/test_margin_trimmer.py -v`

Expected: PASS（既存テストの回帰もないこと）

- [ ] **Step 8: リントを実行する**

Run: `cd C:\AI\face-detective && venv\Scripts\python.exe -m ruff check backend/spread_splitter.py backend/tests/test_spread_splitter.py`

Expected: `All checks passed!`

- [ ] **Step 9: コミット**

```bash
git add backend/spread_splitter.py backend/tests/test_spread_splitter.py
git commit -m "feat: 見開き分割経路に余白トリミングを統合（読み込み時と分割後の2段）"
```

---

### Task 3: `job_manager` の配線と通常経路

**Files:**
- Modify: `backend/job_manager.py`
- Test: `backend/tests/test_job_manager_trim.py`（新規）

**Interfaces:**
- Consumes:
  - `margin_trimmer.trim_image_margins(image) -> tuple[Image.Image, TrimResult]`（Task 1）
  - `process_spread(image_path, count_persons_fn, trim_margins=False)`（Task 2）
- Produces:
  - `JobState.__init__(..., trim_margins: bool = False)` と属性 `JobState.trim_margins`
  - `JobManager.register_job(..., trim_margins: bool = False)`（`_pending` に `"trim_margins"` キーを格納）
  - `JobManager.start_job(..., trim_margins: bool = False)`
  - `JobManager._process_single_file(state: JobState, file_path: Path) -> None`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_job_manager_trim.py` を新規作成する:

```python
"""job_manager の余白トリミング配線に関するテスト。

顔検出は重い外部依存のためモックし、
「トリミングの有無で保存経路が切り替わるか」だけを検証する。
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw

import job_manager as job_manager_module
from job_manager import JobManager, JobState


def _make_state(
    tmp_path: Path,
    *,
    trim_margins: bool,
) -> tuple[JobState, Path]:
    """テスト用の JobState と入力画像パスを作成する。

    800x600 の白背景の中央に 400x400 のコンテンツを置いた画像を作る。

    Args:
        tmp_path: pytest の一時ディレクトリ。
        trim_margins: 余白トリミングを有効にするかどうか。

    Returns:
        (JobState, 入力画像パス) のタプル。
    """
    source = tmp_path / "src"
    dest = tmp_path / "dest"
    source.mkdir()
    dest.mkdir()

    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    ImageDraw.Draw(img).rectangle((200, 100, 599, 499), fill=(120, 60, 60))
    image_path = source / "page.png"
    img.save(image_path)

    state = JobState(
        job_id="test-job",
        source_folder=source,
        dest_folder=dest,
        threshold=1.0,
        trim_margins=trim_margins,
    )
    return state, image_path


def _patch_face_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """顔検出を「常に抽出対象」を返すモックに差し替える。

    Args:
        monkeypatch: pytest の monkeypatch フィクスチャ。
    """
    result = {
        "should_move": True,
        "max_face_ratio": 10.0,
        "both_eyes_visible": True,
    }
    monkeypatch.setattr(
        job_manager_module, "detect_faces", MagicMock(return_value=result)
    )
    monkeypatch.setattr(
        job_manager_module,
        "detect_faces_from_array",
        MagicMock(return_value=result),
    )


class TestJobStateTrimMargins:
    """JobState の trim_margins 属性のテストクラス。"""

    def test_defaults_to_false(self, tmp_path: Path) -> None:
        """trim_margins を省略すると False になること。"""
        state = JobState(
            job_id="j",
            source_folder=tmp_path,
            dest_folder=tmp_path,
            threshold=5.0,
        )
        assert state.trim_margins is False

    def test_register_job_stores_flag(self, tmp_path: Path) -> None:
        """register_job が trim_margins を pending に保持すること。"""
        manager = JobManager()
        job_id, _dest = manager.register_job(
            source_folder=str(tmp_path), threshold=5.0, trim_margins=True
        )
        assert manager._pending[job_id]["trim_margins"] is True


class TestProcessSingleFile:
    """_process_single_file のテストクラス。"""

    def test_copies_without_trimming_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """トリミング無効時は元画像がそのままのサイズでコピーされること。"""
        _patch_face_detection(monkeypatch)
        state, image_path = _make_state(tmp_path, trim_margins=False)

        JobManager()._process_single_file(state, image_path)

        saved = list(state.dest_folder.rglob("*.png"))
        assert len(saved) == 1
        assert Image.open(saved[0]).size == (800, 600)
        assert state.extracted == 1

    def test_trims_and_reencodes_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """トリミング有効時はコンテンツ矩形だけが保存されること。"""
        _patch_face_detection(monkeypatch)
        state, image_path = _make_state(tmp_path, trim_margins=True)

        JobManager()._process_single_file(state, image_path)

        saved = list(state.dest_folder.rglob("*.png"))
        assert len(saved) == 1
        assert Image.open(saved[0]).size == (400, 400)
        assert state.extracted == 1

    def test_face_ratio_uses_trimmed_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """顔検出にトリミング後のサイズが渡されること。"""
        _patch_face_detection(monkeypatch)
        state, image_path = _make_state(tmp_path, trim_margins=True)

        JobManager()._process_single_file(state, image_path)

        call = job_manager_module.detect_faces_from_array.call_args
        # 位置引数は (image_array, width, height, threshold)
        assert call.args[1] == 400
        assert call.args[2] == 400

    def test_skips_when_face_below_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """閾値未満の画像は保存されず skipped が増えること。"""
        monkeypatch.setattr(
            job_manager_module,
            "detect_faces_from_array",
            MagicMock(
                return_value={
                    "should_move": False,
                    "max_face_ratio": 0.5,
                    "both_eyes_visible": False,
                }
            ),
        )
        state, image_path = _make_state(tmp_path, trim_margins=True)

        JobManager()._process_single_file(state, image_path)

        assert list(state.dest_folder.rglob("*.png")) == []
        assert state.skipped == 1
        assert state.extracted == 0
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/test_job_manager_trim.py -v`

Expected: FAIL — `TypeError: JobState.__init__() got an unexpected keyword argument 'trim_margins'`

- [ ] **Step 3: `job_manager.py` の import を追加する**

既存の import ブロックを以下に置き換える（`numpy` は `_process_spread_file` 内でローカル import されているが、通常経路でも必要になるためトップレベルに引き上げる）:

```python
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from face_detector import detect_faces, detect_faces_from_array
from file_scanner import scan_folder
from image_copier import copy_image, generate_dest_folder, save_spread_image
from margin_trimmer import trim_image_margins
from person_detector import count_persons
from spread_splitter import process_spread
```

`_process_spread_file` の中にある `import numpy as np` の行は削除する（トップレベルに移したため）。

- [ ] **Step 4: `JobState` に `trim_margins` を追加する**

`JobState.__init__` の引数リストで、`spread_split: bool = False,` の**次の行**に追加する:

```python
        trim_margins: bool = False,
```

docstring の `Args:` で `spread_split: 見開き分割を有効にするかどうか。` の次に追加する:

```
            trim_margins: 白／黒の余白トリミングを有効にするかどうか。
```

`self.spread_split = spread_split` の次の行に追加する:

```python
        self.trim_margins = trim_margins
```

- [ ] **Step 5: `register_job` と `start_job` に伝搬させる**

`register_job` の引数リストで `spread_split: bool = False,` の次に `trim_margins: bool = False,` を追加し、docstring の `Args:` にも 1 行足す。`self._pending[job_id]` の辞書リテラルで `"spread_split": spread_split,` の次に追加する:

```python
            "trim_margins": trim_margins,
```

`start_job` も同様に引数 `trim_margins: bool = False,` を `spread_split: bool = False,` の次に追加し、docstring に 1 行足す。`JobState(...)` の呼び出しで `spread_split=spread_split,` の次に追加する:

```python
            trim_margins=trim_margins,
```

同じく `start_job` のログ行を更新する:

```python
        logger.info(
            "ジョブを開始します: job_id=%s, spread_split=%s, trim_margins=%s",
            job_id, spread_split, trim_margins,
        )
```

- [ ] **Step 6: 通常経路を `_process_single_file` に切り出す**

`_run_job` のループ内にある `if state.spread_split:` ブロックを、以下に置き換える:

```python
                if state.spread_split:
                    self._process_spread_file(state, file_path)
                else:
                    self._process_single_file(state, file_path)
```

そして `_process_spread_file` の定義の**直前**に新しいメソッドを追加する:

```python
    def _process_single_file(self, state: JobState, file_path: Path) -> None:
        """見開き分割なしの通常経路で 1 ファイルを処理する。

        ``state.trim_margins`` が無効な場合は従来どおりパス指定の顔検出を行い、
        条件を満たせば ``shutil.copy2`` によるバイトコピーで保存する（無劣化）。

        有効な場合は画像を開いて余白をトリミングし、その結果に対して顔検出を行う。
        こうすることで顔面積比が「実際の写真に対する比率」になる。実際に
        トリミングが発生した画像だけを再エンコードして保存し、発生しなかった
        画像は従来どおりバイトコピーに戻すことで無駄な再圧縮を避ける。

        Args:
            state: 実行中のジョブ状態オブジェクト。
            file_path: 処理対象の画像ファイルパス。
        """
        if not state.trim_margins:
            result = detect_faces(
                file_path, state.threshold,
                min_eye_ratio=state.min_eye_ratio,
                min_face_score=state.min_face_score,
            )
            if result["should_move"] and (
                not state.require_both_eyes or result["both_eyes_visible"]
            ):
                copy_image(
                    file_path, state.source_folder, state.dest_folder,
                    face_ratio=result["max_face_ratio"],
                    both_eyes_visible=result["both_eyes_visible"],
                )
                state.extracted += 1
            else:
                state.skipped += 1
            return

        raw_image = Image.open(file_path)
        raw_image = ImageOps.exif_transpose(raw_image)
        image = raw_image.convert("RGB")
        image, trim_info = trim_image_margins(image)
        if trim_info["trimmed"]:
            logger.info(
                "余白をトリミングしました: %s — 残率 %.0f%%",
                file_path, trim_info["keep_ratio"] * 100,
            )

        image_array = np.array(image, dtype=np.uint8)
        result = detect_faces_from_array(
            image_array, image.width, image.height, state.threshold,
            min_eye_ratio=state.min_eye_ratio,
            min_face_score=state.min_face_score,
        )

        if not (
            result["should_move"]
            and (not state.require_both_eyes or result["both_eyes_visible"])
        ):
            state.skipped += 1
            return

        if trim_info["trimmed"]:
            # トリミングで画素が変わっているため再エンコードが必要
            save_spread_image(
                image, file_path, "",
                state.source_folder, state.dest_folder,
                face_ratio=result["max_face_ratio"],
                both_eyes_visible=result["both_eyes_visible"],
            )
        else:
            copy_image(
                file_path, state.source_folder, state.dest_folder,
                face_ratio=result["max_face_ratio"],
                both_eyes_visible=result["both_eyes_visible"],
            )
        state.extracted += 1
```

- [ ] **Step 7: `_process_spread_file` に `trim_margins` を渡す**

`_process_spread_file` 内の `process_spread` 呼び出しを更新する:

```python
        spread_result = process_spread(
            file_path, _count_fn, trim_margins=state.trim_margins
        )
```

- [ ] **Step 8: テストを実行して成功を確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/ -v`

Expected: PASS（全テスト。既存テストの回帰もないこと）

- [ ] **Step 9: リントを実行する**

Run: `cd C:\AI\face-detective && venv\Scripts\python.exe -m ruff check backend/job_manager.py backend/tests/test_job_manager_trim.py`

Expected: `All checks passed!`

- [ ] **Step 10: コミット**

```bash
git add backend/job_manager.py backend/tests/test_job_manager_trim.py
git commit -m "feat: job_manager に余白トリミングを配線し通常経路を _process_single_file に切り出し"
```

---

### Task 4: API エンドポイント

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_main_routes.py`

**Interfaces:**
- Consumes: `JobManager.register_job(..., trim_margins=False)` / `JobManager.start_job(..., trim_margins=False)`（Task 3）
- Produces: `StartJobRequest.trim_margins: bool = False`（POST `/api/start` の JSON フィールド `trim_margins`）

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_main_routes.py` の末尾に追加する:

```python
@pytest.mark.parametrize("prefix", PREFIXES)
def test_start_accepts_trim_margins(
    client: TestClient, tmp_path, prefix: str,
) -> None:
    """POST /api/start が trim_margins を受け取り pending に保持すること。"""
    from main import job_manager

    resp = client.post(
        f"{prefix}/api/start",
        json={
            "source_folder": str(tmp_path),
            "threshold": 5.0,
            "trim_margins": True,
        },
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert job_manager._pending[job_id]["trim_margins"] is True


@pytest.mark.parametrize("prefix", PREFIXES)
def test_start_defaults_trim_margins_to_false(
    client: TestClient, tmp_path, prefix: str,
) -> None:
    """trim_margins を省略した場合は False になること（後方互換）。"""
    from main import job_manager

    resp = client.post(
        f"{prefix}/api/start",
        json={"source_folder": str(tmp_path), "threshold": 5.0},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert job_manager._pending[job_id]["trim_margins"] is False
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/test_main_routes.py -k trim_margins -v`

Expected: FAIL — `KeyError: 'trim_margins'`

- [ ] **Step 3: `main.py` を更新する**

`StartJobRequest` で `spread_split: bool = False` の次の行に追加する:

```python
    trim_margins: bool = False
```

`start_job` ハンドラの `job_manager.register_job(...)` 呼び出しで `spread_split=request.spread_split,` の次に追加する:

```python
        trim_margins=request.trim_margins,
```

同ハンドラのログ行を更新する:

```python
    logger.info(
        "ジョブ登録: job_id=%s, src=%s, dest=%s, threshold=%.1f, spread_split=%s, trim_margins=%s",
        job_id,
        request.source_folder,
        dest_folder,
        request.threshold,
        request.spread_split,
        request.trim_margins,
    )
```

WebSocket ハンドラの `job_manager.start_job(...)` 呼び出しで `spread_split=pending.get("spread_split", False),` の次に追加する:

```python
        trim_margins=pending.get("trim_margins", False),
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/ -v`

Expected: PASS（全テスト）

- [ ] **Step 5: リントを実行する**

Run: `cd C:\AI\face-detective && venv\Scripts\python.exe -m ruff check backend/`

Expected: `All checks passed!`

- [ ] **Step 6: コミット**

```bash
git add backend/main.py backend/tests/test_main_routes.py
git commit -m "feat: POST /api/start に trim_margins フィールドを追加"
```

---

### Task 5: フロントエンドの設定 UI

**Files:**
- Modify: `frontend/src/components/SettingsForm.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: POST `/api/start` の JSON フィールド `trim_margins: boolean`（Task 4）
- Produces: `SettingsFormProps.onStart(source, threshold, spreadSplit, trimMargins, requireBothEyes, advanced)`

> 引数を位置引数の 4 番目に挿入する。`App.tsx` の `handleStart` も同じ順序に合わせること。既存の `requireBothEyes` 以降が 1 つずつ後ろにずれる。

- [ ] **Step 1: `SettingsForm.tsx` の Props 型を更新する**

`SettingsFormProps` の `onStart` を書き換える:

```tsx
  /** スキャン開始時のコールバック */
  onStart: (
    source: string,
    threshold: number,
    spreadSplit: boolean,
    trimMargins: boolean,
    requireBothEyes: boolean,
    advanced: AdvancedSettings,
  ) => void
```

- [ ] **Step 2: `SettingsForm.tsx` に state を追加する**

`spreadSplit` の `useState` の**次**に追加する:

```tsx
  const [trimMargins, setTrimMargins] = useState(() => {
    return localStorage.getItem('face-detective-trimMargins') === 'true'
  })
```

- [ ] **Step 3: `handleSubmit` を更新する**

`localStorage.setItem('face-detective-spreadSplit', String(spreadSplit))` の次の行に追加する:

```tsx
    localStorage.setItem('face-detective-trimMargins', String(trimMargins))
```

`onStart` の呼び出しを書き換える:

```tsx
    onStart(sourcePath.trim(), threshold, spreadSplit, trimMargins, requireBothEyes, {
      minEyeRatio: minEyeRatio / 100,
      minFaceScore: minFaceScore / 100,
      yoloConfidence: yoloConfidence / 100,
    })
```

- [ ] **Step 4: チェックボックスを追加する**

`{/* 見開き分割オプション */}` のブロック全体の**直後**（`{/* 両目フィルタオプション */}` の直前）に挿入する:

```tsx
      {/* 余白トリミングオプション */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={trimMargins}
            onChange={(e) => setTrimMargins(e.target.checked)}
            disabled={disabled}
            className="w-4 h-4 text-blue-500 rounded border-gray-300 focus:ring-blue-500 disabled:cursor-not-allowed"
          />
          <span className="text-sm font-medium text-gray-700">余白（白・黒）をトリミング</span>
        </label>
        <p className="text-xs text-gray-400 ml-6">
          電子書籍リーダーのスクリーンショットなど、写真の周囲に白または黒の余白がある画像から写真部分だけを切り出します。顔サイズの割合も切り出し後の写真を基準に計算されます
        </p>
      </div>
```

- [ ] **Step 5: `App.tsx` の `handleStart` を更新する**

引数リストに `trimMargins` を追加する:

```tsx
  const handleStart = async (
    source: string,
    threshold: number,
    spreadSplit: boolean,
    trimMargins: boolean,
    requireBothEyes: boolean,
    advanced: { minEyeRatio: number; minFaceScore: number; yoloConfidence: number },
  ) => {
```

`body: JSON.stringify({...})` の `spread_split: spreadSplit,` の次の行に追加する:

```tsx
          trim_margins: trimMargins,
```

- [ ] **Step 6: 型チェックとビルドを実行する**

Run: `cd C:\AI\face-detective\frontend && npm run build`

Expected: TypeScript のエラーなしでビルドが完了する。エラーが出た場合は `onStart` の引数順序が `SettingsForm.tsx` と `App.tsx` で一致しているか確認する。

- [ ] **Step 7: `/face-detect` ベースでビルドし直す**

バックエンドは `frontend/dist` を `/` と `/face-detect` の両方で配信するため、`VITE_BASE_PATH` を付けてビルドする。

Run (PowerShell): `cd C:\AI\face-detective\frontend; $env:VITE_BASE_PATH='/face-detect/'; npm run build`

Expected: `dist/index.html` 内のアセット参照が `/face-detect/assets/...` になっていること。

Run: `grep -o '/face-detect/assets/[^"]*' C:\AI\face-detective\frontend\dist\index.html`

- [ ] **Step 8: コミット**

`frontend/dist/` は `.gitignore` に含まれており git 管理外なので、ソースだけをコミットする。

```bash
git add frontend/src/components/SettingsForm.tsx frontend/src/App.tsx
git commit -m "feat: 余白トリミングのチェックボックスを設定フォームに追加"
```

---

### Task 6: 実データでの動作確認

**Files:**
- Test: 手動確認（コード変更なし）

**Interfaces:**
- Consumes: Task 1〜5 のすべて
- Produces: なし（検証のみ）

- [ ] **Step 1: バックエンドを起動する**

Run: `C:\AI\LLM-prompt\Launcher\start-face-detect.bat`

Expected: `Uvicorn running on http://127.0.0.1:52840` と、リロード有効のメッセージが表示される。

- [ ] **Step 2: 全テストを最終確認する**

Run: `cd C:\AI\face-detective\backend && ..\venv\Scripts\python.exe -m pytest tests/ -v`

Expected: 全 PASS。失敗が 1 件でもあればここで止めて修正する。

- [ ] **Step 3: ブラウザで実データを処理する**

`http://127.0.0.1:52840/` を開き、以下の設定でスキャンする。

- 入力フォルダ: `C:\Users\MANAx2-SUB\Pictures\Images_library_face\raw\ちとせよしの kiss you 3`
- 顔サイズ閾値: 5%
- 見開き分割: ON
- 余白をトリミング: ON

出力先は `...\ちとせよしの kiss you 3_face` に自動生成される。

- [ ] **Step 4: 出力を検証する**

出力フォルダの画像を確認し、以下を満たすこと。

- 画像に白余白が残っていない（写真部分だけが切り出されている）
- ファイル名の `_N.Npct` が従来の 2〜7% から 7〜25% 程度に上がっている
- ページが欠落していない（`page_0006` 相当の見開きから 2 枚とも出ている）

`backend/logs/` のログに `余白をトリミングしました` の行が出ていることも確認する。

- [ ] **Step 5: 回帰確認 — 余白のない素材で無変化であること**

同じ手順で、余白のない素材のフォルダをスキャンする。

- 入力フォルダ: `C:\Users\MANAx2-SUB\Pictures\Images_library_face\raw\小日向ゆり yuri mode Newtopia 348P (ELD)`

出力画像のサイズが元画像と同じ（1385×2076 系）であり、トリミングが発生していないことを確認する。ログに `余白は検出されませんでした` が出る（DEBUG レベルのため、必要なら一時的にログレベルを下げる）。

- [ ] **Step 6: 閾値の再調整について記録する**

顔面積比の算出基準が変わったため、Step 4 で出力されたファイル名の `_N.Npct` を集計し、
spec の「影響範囲 → 出力ファイル名の非互換」節の末尾に実測値を追記する。記載する内容は次の 3 つ:

- トリミング前の面積比の範囲（例: 2.0〜7.9%）
- トリミング後の面積比の範囲
- 従来と同等の選別結果を得るための推奨閾値（トリミング後の分布の中央値付近）

- [ ] **Step 7: コミットとマージ**

```bash
git add -A
git commit -m "docs: 余白トリミング導入後の推奨閾値を記録"
git checkout main
git merge --no-ff feature/margin-trim -m "Merge: 余白トリミング機能を追加"
```
