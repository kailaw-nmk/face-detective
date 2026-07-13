# 見開き分割の改善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 見開き分割時に両端の黒マスクを除去し、中央 1 人の写真が誤って見切れ分割されないようにする。

**Architecture:** `spread_splitter.py` に左右黒マスクの検出・トリミング関数を追加し、`process_spread` の処理順を「黒マスク除去 → 綴じ目検出 → 全体人数カウント → (綴じ目あり AND 2人以上) のときのみ分割」に再構成する。人数カウントは中央またぎを誤カウントする `count_persons_split` から全体ボックス数の `count_persons` に切り替える。

**Tech Stack:** Python 3.12 / Pillow / NumPy / pytest。既存の venv は `C:\AI\face-detective\venv`。

## Global Constraints

- テストは backend ディレクトリから実行する: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -m pytest ...`
- `tests/conftest.py` が backend をパスに追加し mediapipe / ultralytics / pillow_heif をスタブ化する。テストで実モデルはロードしない。
- 既存の公開シグネチャと `SpreadResult` のキー（`action`, `face_count`, `stripe_detected`, `images`, `suffixes`, `face_detection`）は維持する。
- 個別ファイルのエラーは握りつぶさずログ出力し、フォールバックで処理を継続する（既存方針）。
- コメント・docstring は日本語。PEP 8 準拠。

---

### Task 1: 黒マスク検出 `detect_side_masks`

**Files:**
- Modify: `backend/spread_splitter.py`（先頭に定数追加、`detect_center_stripe` の前に新関数を追加）
- Test: `backend/tests/test_spread_splitter.py`（新クラス `TestDetectSideMasks` を追加）

**Interfaces:**
- Produces: `detect_side_masks(image: PIL.Image.Image) -> tuple[int, int]` — 残すコンテンツ領域の x 範囲 `(content_left, content_right)` を返す（`content_right` は exclusive）。黒帯がなければ `(0, width)`。
- Produces 定数: `DARK_THRESHOLD=20.0`, `DARK_PIXEL_RATIO=0.95`, `MAX_MASK_RATIO=0.40`, `MIN_MASK_WIDTH=5`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_spread_splitter.py` の import に `detect_side_masks` を追加し、末尾に以下を追加する。

```python
from spread_splitter import (  # 既存 import に detect_side_masks, crop_side_masks を追加
    SpreadResult,
    crop_side_masks,
    detect_center_stripe,
    detect_side_masks,
    process_spread,
    remove_stripe,
    split_at_center,
)


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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -m pytest tests/test_spread_splitter.py::TestDetectSideMasks -v`
Expected: FAIL（`ImportError: cannot import name 'detect_side_masks'`）

- [ ] **Step 3: 定数と `detect_side_masks` を実装**

`backend/spread_splitter.py` の `logger = logging.getLogger(__name__)` の直後に定数を追加する。

```python
# 黒マスク（レターボックス）検出パラメータ
DARK_THRESHOLD = 20.0      # 黒とみなす列平均輝度の上限（0–255）
DARK_PIXEL_RATIO = 0.95    # 列内で暗いピクセルが占める最低割合
MAX_MASK_RATIO = 0.40      # 片側除去幅の上限（画像幅比。暴走防止）
MIN_MASK_WIDTH = 5         # これ未満の黒帯は無視
```

`detect_center_stripe` 関数定義の直前に以下を追加する。

```python
def detect_side_masks(image: Image.Image) -> tuple[int, int]:
    """画像左右端の黒マスク（縦の黒帯）を検出し、残すコンテンツ領域を返す。

    左右端から中央に向かって「暗い列」が連続する範囲を黒マスクとみなす。
    列平均輝度と暗ピクセル率の両方で判定することで、反対側に明るい被写体が
    あっても黒帯だけを正しく識別する。

    Args:
        image: 処理対象の PIL 画像（RGB を想定）。

    Returns:
        残すコンテンツ領域の x 範囲 (content_left, content_right)。
        content_right は exclusive。黒帯がなければ (0, width)。
    """
    rgb = image.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32)  # shape: (H, W, 3)
    width = arr.shape[1]

    col_mean = arr.mean(axis=(0, 2))               # 各列の平均輝度 (W,)
    pixel_lum = arr.mean(axis=2)                    # 各ピクセル輝度 (H, W)
    dark_ratio = (pixel_lum < DARK_THRESHOLD).mean(axis=0)  # 列ごとの暗ピクセル率 (W,)
    is_dark = (col_mean < DARK_THRESHOLD) & (dark_ratio > DARK_PIXEL_RATIO)  # (W,)

    max_mask = int(width * MAX_MASK_RATIO)

    # 左端から連続する暗い列
    left = 0
    while left < width and bool(is_dark[left]):
        left += 1
    if left < MIN_MASK_WIDTH:
        left = 0
    else:
        left = min(left, max_mask)

    # 右端から連続する暗い列（content_right は exclusive）
    right = width
    while right > 0 and bool(is_dark[right - 1]):
        right -= 1
    if (width - right) < MIN_MASK_WIDTH:
        right = width
    else:
        right = max(right, width - max_mask)

    if right <= left:
        # 全体が暗い等の異常時はトリミングしない
        logger.debug("黒マスク検出: content 領域が無効のためトリミングなし")
        return (0, width)

    if left != 0 or right != width:
        logger.debug("黒マスクを検出 — content x=[%d, %d)", left, right)
    return (left, right)
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -m pytest tests/test_spread_splitter.py::TestDetectSideMasks -v`
Expected: PASS（5 件）

- [ ] **Step 5: コミット**

```bash
cd C:\AI\face-detective
git add backend/spread_splitter.py backend/tests/test_spread_splitter.py
git commit -m "feat: 左右黒マスク検出 detect_side_masks を追加"
```

---

### Task 2: 黒マスクトリミング `crop_side_masks`

**Files:**
- Modify: `backend/spread_splitter.py`（`detect_side_masks` の直後に追加）
- Test: `backend/tests/test_spread_splitter.py`（新クラス `TestCropSideMasks` を追加）

**Interfaces:**
- Consumes: `detect_side_masks` の戻り値 `(content_left, content_right)`
- Produces: `crop_side_masks(image: PIL.Image.Image, content_left: int, content_right: int) -> PIL.Image.Image` — 指定範囲でトリミングした画像。`(0, width)` のときは元画像をそのまま返す。

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_spread_splitter.py` の末尾に追加する。

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -m pytest tests/test_spread_splitter.py::TestCropSideMasks -v`
Expected: FAIL（`ImportError: cannot import name 'crop_side_masks'`）

- [ ] **Step 3: `crop_side_masks` を実装**

`backend/spread_splitter.py` の `detect_side_masks` の直後に追加する。

```python
def crop_side_masks(
    image: Image.Image,
    content_left: int,
    content_right: int,
) -> Image.Image:
    """左右の黒マスクを除去したトリミング画像を返す。

    Args:
        image: 処理対象の PIL 画像。
        content_left: 残すコンテンツ領域の左端 x 座標。
        content_right: 残すコンテンツ領域の右端 x 座標（exclusive）。

    Returns:
        トリミング後の PIL 画像。トリミング不要（0, width）の場合は元画像をそのまま返す。
    """
    width, height = image.size
    if content_left <= 0 and content_right >= width:
        return image
    return image.crop((content_left, 0, content_right, height))
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -m pytest tests/test_spread_splitter.py::TestCropSideMasks -v`
Expected: PASS（2 件）

- [ ] **Step 5: コミット**

```bash
cd C:\AI\face-detective
git add backend/spread_splitter.py backend/tests/test_spread_splitter.py
git commit -m "feat: 黒マスクトリミング crop_side_masks を追加"
```

---

### Task 3: `process_spread` の再構成（黒マスク除去 + AND 分割条件）

**Files:**
- Modify: `backend/spread_splitter.py`（`process_spread` の本体）
- Test: `backend/tests/test_spread_splitter.py`（`TestProcessSpread` に統合テストを追加）

**Interfaces:**
- Consumes: `detect_side_masks`, `crop_side_masks`（Task 1/2）、`detect_center_stripe`, `remove_stripe`, `split_at_center`（既存）
- Produces: `process_spread(image_path, count_persons_fn) -> SpreadResult` — 処理順は「黒マスク除去 → 綴じ目検出/除去 → 全体人数カウント → (綴じ目あり AND 人数≥2) のときのみ分割」。分割トリガーが `stripe_detected and person_count >= 2` に変わる。

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_spread_splitter.py` の `TestProcessSpread` クラス内（`_make_spread_image_file` の後）に、黒帯付き画像ヘルパーと新テストを追加する。

```python
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

    def test_no_split_when_two_persons_but_no_stripe(self, tmp_path: Path) -> None:
        """人数 2 でも綴じ目がなければ分割しないこと（問題2の修正）。"""
        image_path = self._make_spread_image_file(tmp_path, with_stripe=False)
        count_fn = _make_count_persons_fn(person_count=2)

        result = process_spread(image_path, count_fn)

        assert result["action"] == "no_stripe", f"action が 'no_stripe' のはず: {result['action']}"
        assert len(result["images"]) == 1, "分割されないので画像は 1 枚"
        assert result["suffixes"] == [""]

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
        """黒帯+中央1人（綴じ目なし）→ 分割されずトリミングのみ（問題2の修正）。"""
        image_path = self._make_masked_spread_file(tmp_path, with_stripe=False)
        count_fn = _make_count_persons_fn(person_count=1)

        result = process_spread(image_path, count_fn)

        assert result["action"] == "no_stripe", f"action が 'no_stripe' のはず: {result['action']}"
        assert len(result["images"]) == 1
        # トリミングで幅が元の 1000 より小さくなっている（黒帯 200px 除去 → 約 800）
        assert result["images"][0].width < 1000, "黒帯がトリミングされていない"
        # 左右端が黒でない
        arr = np.asarray(result["images"][0])
        assert arr[:, 0, :].mean() > 30, "左端に黒帯が残っている"
        assert arr[:, -1, :].mean() > 30, "右端に黒帯が残っている"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -m pytest tests/test_spread_splitter.py::TestProcessSpread -v`
Expected: FAIL（`test_no_split_when_two_persons_but_no_stripe` は現状 split になる、黒帯系は黒帯が残る、など新テストが失敗）

- [ ] **Step 3: `process_spread` を再構成**

`backend/spread_splitter.py` の `process_spread` 内、画像読み込み直後（`logger.debug("画像を読み込みました...` の行の後）から分割判定までを以下で置き換える。

置換前（現状）:
```python
    logger.debug("画像を読み込みました: %s (%dx%d)", image_path, *original.size)

    # ストライプ検出
    stripe_info: tuple[int, int] | None = None
    try:
        stripe_info = detect_center_stripe(original)
```

置換後:
```python
    logger.debug("画像を読み込みました: %s (%dx%d)", image_path, *original.size)

    # 左右の黒マスクを検出してトリミングする（分割の有無に関わらず常に適用）
    try:
        content_left, content_right = detect_side_masks(original)
    except Exception as exc:
        logger.error(
            "黒マスク検出中にエラーが発生しました。トリミングをスキップします — %s: %s",
            image_path, exc, exc_info=True,
        )
        content_left, content_right = 0, original.size[0]
    base_image = crop_side_masks(original, content_left, content_right)
    if base_image is not original:
        logger.info(
            "黒マスクをトリミングしました: %s — %dx%d → %dx%d",
            image_path, *original.size, *base_image.size,
        )

    # ストライプ検出（トリミング後の画像に対して実行）
    stripe_info: tuple[int, int] | None = None
    try:
        stripe_info = detect_center_stripe(base_image)
```

次に、ストライプ除去の分岐で `original` を `base_image` に変える。

置換前:
```python
        working_image = remove_stripe(original, stripe_info[0], stripe_info[1])
    else:
        logger.debug("ストライプは検出されませんでした: %s", image_path)
        working_image = original
```

置換後:
```python
        working_image = remove_stripe(base_image, stripe_info[0], stripe_info[1])
    else:
        logger.debug("ストライプは検出されませんでした: %s", image_path)
        working_image = base_image
```

最後に分割判定を AND 条件に変える。

置換前:
```python
    # 人物数に応じて分割判定を行う
    if person_count >= 2:
```

置換後:
```python
    # 分割判定: 綴じ目ストライプ検出 AND 人物数 >= 2 の両方成立時のみ分割する
    should_split = stripe_detected and person_count >= 2
    if should_split:
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -m pytest tests/test_spread_splitter.py -v`
Expected: PASS（既存 + 新規すべて。既存 `test_process_spread_split_2_persons` は stripe あり×2人でそのまま split）

- [ ] **Step 5: コミット**

```bash
cd C:\AI\face-detective
git add backend/spread_splitter.py backend/tests/test_spread_splitter.py
git commit -m "feat: 見開き処理を黒マスク除去+AND分割条件に再構成"
```

---

### Task 4: `job_manager` の人数カウントを全体ボックス数に切り替え

**Files:**
- Modify: `backend/job_manager.py:16`（import）と `backend/job_manager.py:358-361`（`_count_fn`）

**Interfaces:**
- Consumes: `person_detector.count_persons(image_array, confidence) -> int`（既存。YOLO の人物ボックス総数を返す）
- Produces: `_process_spread_file` が全体画像のボックス数で分割判定するようになる（中央またぎの 1 人を 1 人と数える）

- [ ] **Step 1: import を変更**

`backend/job_manager.py` の 16 行目を変更する。

置換前:
```python
from person_detector import count_persons_split
```
置換後:
```python
from person_detector import count_persons
```

- [ ] **Step 2: `_count_fn` を変更**

`backend/job_manager.py` の `_process_spread_file` 内 `_count_fn`（現状 358-361 行付近）を変更する。

置換前:
```python
        def _count_fn(arr: np.ndarray) -> int:
            return count_persons_split(arr, confidence=state.yolo_confidence)
```
置換後:
```python
        def _count_fn(arr: np.ndarray) -> int:
            # 全体画像の人物ボックス総数で判定する
            # （左右分割カウントは中央またぎの 1 人を 2 人と誤カウントするため使わない）
            return count_persons(arr, confidence=state.yolo_confidence)
```

- [ ] **Step 3: 構文・import 確認**

Run: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -c "import job_manager; print('OK')"`
Expected: `OK`（ImportError や NameError が出ないこと）

- [ ] **Step 4: 全テスト実行（回帰確認）**

Run: `cd C:\AI\face-detective\backend && ../venv/Scripts/python.exe -m pytest -v`
Expected: PASS（全テスト。既存の他モジュールテスト含む）

- [ ] **Step 5: コミット**

```bash
cd C:\AI\face-detective
git add backend/job_manager.py
git commit -m "fix: 見開き人数カウントを全体ボックス数(count_persons)に切替"
```

---

## 完了後の手動確認（任意）

実画像での確認手順:
1. `start.bat` で起動
2. 問題1相当（黒帯+見開き2人）フォルダで見開き分割 ON → `_L`/`_R` に黒帯が残らないこと
3. 問題2相当（黒帯+中央1人）フォルダ → 分割されず、黒帯が除去された 1 枚が出力されること
4. `backend/logs/` のログで「黒マスクをトリミングしました」「分割」判定を確認
