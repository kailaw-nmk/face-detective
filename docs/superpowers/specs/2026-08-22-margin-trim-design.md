# 余白トリミング機能 — 設計仕様書

作成日: 2026-08-22

## 背景と課題

出力画像に大面積の白領域が残る事例が報告された。当初は見開き分割の副作用と推測されたが、
実サンプル (`C:\Users\MANAx2-SUB\Pictures\Images_library_face\raw\ちとせよしの kiss you 3`) を
調査した結果、**原因は元素材そのものにある**ことが判明した。

### 実際の原因: Kindle リーダー UI の写り込み

元画像は Kindle リーダーのフルスクリーン・スクリーンショットであり、以下が白背景ごと
写り込んでいる。

- 左上の「Kindle Library」ボタン
- 上部中央のタイトル文字列
- 左右の前後ページ送り矢印 (`<` `>`)
- 下部の Location プログレスバー
- 開いたままのオーバーフローメニュー

`page_0006` の場合、2460×1375 のうち実際の写真は 645×954 が 2 枚のみで、**画像面積の 66% が
余白**である。既存の `spread_splitter.detect_side_masks()` は黒帯のみを対象としているため、
白余白は素通りしていた。

### 副作用: 顔面積比の希釈

顔面積比は `最大顔面積 / 画像面積 × 100` で算出されるため、余白がそのまま分母を膨らませている。
`page_0011_L` はファイル名が `2.6pct` だが、写真領域のみで再計算すると約 7% になる。
結果として **Kindle 由来の素材だけが閾値判定で不当に不利**になっていた。

### 実測データ

87 枚を「白 (>240) でも黒 (<15) でもない画素」の連結成分で解析した結果:

| 成分数 | 枚数 | 意味 |
|--------|------|------|
| 1 | 79 | 単ページ表示 |
| 2 | 8 | 見開き表示（左右のページが白ガターで分離） |

成分の位置・サイズは極めて安定している（例: 全ての見開きで `(528,77,645×954)` と
`(1288,77,645×954)`）。Kindle の UI ボタン・文字は面積が小さく、面積比 0.2% の足切りで
自然に除外される。

## 設計判断

### 判断1: 実行位置 — 読み込み直後と分割後の二段

```
Image.open + exif_transpose
  ↓
★ trim_margins()            ← 1 回目
  ↓
見開き判定・分割
  ↓
★ trim_margins()            ← 2 回目（分割後の各画像）
  ↓
顔検出 → 面積比算出
  ↓
閾値判定 → 保存
```

顔検出より前でトリミングすることで、顔面積比が「実際の写真に対する比率」となり本来の意味を
取り戻す。見開き判定のアスペクト比も正確になる。分割によって新たに露出する余白（ガターの
片割れ）は 2 回目で除去する。

`page_0006` の追跡例:

| 段階 | サイズ | 内容 |
|------|--------|------|
| 元画像 | 2460×1375 | Kindle スクショ |
| 1 回目トリミング後 | 1405×954 | 外周除去。中央のガター白帯は残る |
| 中央分割後 | 702×954 × 2 | 各半分に残余白あり |
| 2 回目トリミング後 | 645×954 × 2 | 写真のみ |

### 判断2: 最大成分ではなく「全成分の外接矩形の和」を採用

最大の連結成分だけを残す方式は、誌面が複数ブロックに分かれるレイアウトで内容を破壊する。
実測では `声優グランプリ 2026年6月号/page_0036_R` が 3 成分に分かれており、最大成分のみでは
残率 20% となり他の写真を捨ててしまう。

全成分の外接矩形の和を取れば、**削られるのは四辺の均一な余白帯だけ**となり、内容の欠落が
原理的に起きない。73 枚の抜き取り検証で残率が 24% を下回るケースはなかった。

| 残率 | 枚数 | 該当 |
|------|------|------|
| 100%（無変化） | 41 | 余白のない通常素材 |
| 50–90% | 21 | 上下の白帯・黒帯のみ除去 |
| < 50% | 11 | Kindle スクショ素材（狙いどおり） |

視覚確認（赤枠オーバーレイ）でも、声優グランプリ／宮原華音／小間千代／古川真奈美の 4 件すべてで
写真領域が正しく囲まれ、内容の切り落としがないことを確認済み。誌面隅のノンブルが枠外になる
ケースはあるが実害はない。

### 判断3: 独立トグルで両経路に適用

`spread_split` とは独立したチェックボックスとし、見開き分割の ON/OFF に関わらず機能する。
通常経路（`spread_split=False`）では、トリミングが不要と判定された場合は従来どおり
`shutil.copy2` によるバイトコピーを維持し、無駄な再圧縮を避ける。

## コンポーネント設計

### 新規モジュール `backend/margin_trimmer.py`

`spread_splitter.py` が既に 422 行あるため独立モジュールとする。責務は「1 枚の PIL 画像から
余白を除いた矩形を求め、トリミングした画像を返す」ことのみ。ファイル I/O もジョブ状態も持たない。

#### パラメータ（モジュール冒頭に定数化）

| 定数 | 値 | 意味 |
|------|-----|------|
| `WHITE_THRESHOLD` | 240.0 | これより明るい画素は余白候補 |
| `BLACK_THRESHOLD` | 15.0 | これより暗い画素は余白候補 |
| `MIN_COMPONENT_AREA_RATIO` | 0.002 | 画像面積比 0.2% 未満の成分は UI 部品とみなし無視 |
| `OPEN_KERNEL_SIZE` | 9 | モルフォロジー開処理のカーネル一辺 |
| `MIN_KEEP_AREA_RATIO` | 0.05 | 残率がこれ未満なら異常としてトリミング中止 |
| `MIN_OUTPUT_SIZE` | 32 | 出力の幅または高さがこれ未満ならトリミング中止 |

#### 型定義

```python
class TrimResult(TypedDict):
    trimmed: bool                        # 実際にトリミングしたか
    bbox: tuple[int, int, int, int]      # (left, top, right, bottom) — right/bottom は exclusive
    keep_ratio: float                    # 残存面積比 (0.0–1.0)
    reason: str                          # 下表のいずれか
```

`reason` の取りうる値:

| 値 | 意味 | trimmed |
|----|------|---------|
| `"trimmed"` | 正常にトリミングした | True |
| `"no_margin"` | bbox が画像全体と一致（余白なし） | False |
| `"no_content"` | 有効な成分がゼロ（全面が白または黒） | False |
| `"too_aggressive"` | 残率が `MIN_KEEP_AREA_RATIO` 未満 | False |
| `"too_small"` | 出力サイズが `MIN_OUTPUT_SIZE` 未満 | False |
| `"error"` | 検出処理が例外を送出 | False |

#### `detect_content_bbox(image: Image.Image) -> tuple[int, int, int, int] | None`

1. RGB に変換し、輝度 = RGB 3 チャンネルの平均を取る
2. 余白マスク = `(輝度 > WHITE_THRESHOLD) | (輝度 < BLACK_THRESHOLD)`
3. コンテンツマスク = 余白マスクの否定
4. `cv2.morphologyEx(..., MORPH_OPEN, 9×9)` で JPEG リンギングと細い文字を除去
5. `cv2.connectedComponentsWithStats(..., 8)` で連結成分を取得
6. 面積比が `MIN_COMPONENT_AREA_RATIO` 以上の成分のみ採用
7. 採用した全成分の外接矩形の和を返す。成分がゼロなら `None`

`MORPH_CLOSE` は使わない。外接矩形の和を取るため穴埋めは不要であり、閉処理は無関係な成分を
繋げるリスクと計算コストだけが残るため。

#### `trim_margins(image: Image.Image) -> tuple[Image.Image, TrimResult]`

`detect_content_bbox()` を呼び、安全弁を順に評価する。いずれかに該当した場合は
**元の画像オブジェクトをそのまま返す**（`is` 比較で同一性を判定できる）。

安全弁の評価順:

1. bbox が `None` → `no_content`
2. bbox が画像全体と一致 → `no_margin`
3. 出力の幅または高さが `MIN_OUTPUT_SIZE` 未満 → `too_small`
4. 残率が `MIN_KEEP_AREA_RATIO` 未満 → `too_aggressive`
5. それ以外 → `image.crop(bbox)` を返し `trimmed=True`

## エラー処理

既存 `spread_splitter.detect_side_masks()` と同じ方針を踏襲する。

- 検出処理中の例外は `logger.error(..., exc_info=True)` に記録したうえで、
  `reason="error"` かつトリミングなしで処理を継続する
- 個別ファイルのエラーでジョブ全体を止めない

## パイプライン統合

### `spread_splitter.process_spread()`

シグネチャに `trim_margins: bool = False` を追加する。デフォルト `False` により既存の
呼び出し・テストは影響を受けない。

```
1. 画像を開く（EXIF 回転・RGB 変換）              … 既存
2. trim_margins() を適用                          … 新規
3. detect_side_masks / crop_side_masks            … 既存
4. detect_center_stripe / remove_stripe           … 既存
5. 人物数カウント → 分割判定 → split_at_center     … 既存
6. 返す各画像に trim_margins() を適用              … 新規
```

手順 3 はトリミング ON のとき実質的に no-op となるが、トリミング OFF 時の従来動作を保つため
残す。

### `job_manager`

- `JobState` に `trim_margins: bool` を追加し、`start_job` / `_run_job` を経由して伝搬する
- `_process_spread_file()`: `process_spread()` に `trim_margins=state.trim_margins` を渡す
- `_process_file()`（通常経路。現在は `_run_job()` のループ内にインライン展開されている）:
  - `trim_margins` が False → 従来どおり `detect_faces(file_path, ...)` で判定し `copy_image()`
  - `trim_margins` が True → 画像を開いて `trim_margins()` を適用し、その結果の numpy 配列に
    対して既存の `detect_faces_from_array()` で判定する。`trimmed=True` なら
    `save_spread_image()`（`suffix=""`）で再エンコード保存、`trimmed=False` なら
    `copy_image()` のバイトコピーに戻す

見開き分割経路が既に `detect_faces_from_array()` を使っているため、通常経路にトリミングを
入れても顔検出ロジックの重複実装は発生しない。

## API / UI

### Backend

`main.py` の `StartJobRequest` に `trim_margins: bool = False` を追加し、`JobManager.start_job()`
へ渡す。ペンディング辞書 (`pending`) にも同キーで保持する。

### Frontend

`SettingsForm.tsx` に `見開きを分割する` と並列のチェックボックスを追加する。

- ラベル: 「余白（白・黒）をトリミングする」
- 補足文: 「電子書籍リーダーのスクリーンショットなど、写真の周囲に白または黒の余白がある画像から
  写真部分だけを切り出します」
- 状態は `App.tsx` の既存 `useState` 群に追加し、`/api/start` の payload に含める

### 進捗通知

WebSocket に以下の形式でログを流す。

```
余白をトリミング: page_0006.jpg 2460x1375 → 1405x954 (残率 40%)
```

## テスト方針

`backend/tests/test_margin_trimmer.py` を pytest で新規作成する。フィクスチャは
**Pillow で生成する合成画像**とする（実サンプルは性質上リポジトリにコミットしない）。

| ケース | 入力 | 期待 |
|--------|------|------|
| 白枠除去 | 白背景の中央にカラー矩形 | bbox が矩形と一致、`trimmed=True` |
| 黒枠除去 | 黒背景の中央にカラー矩形 | 同上 |
| 白黒混在 | 上下が黒帯、左右が白帯 | 4 辺すべて除去される |
| 余白なし | 全面がカラーノイズ | `reason="no_margin"`、戻り値が入力と同一オブジェクト |
| 全面白 | 純白のみ | `reason="no_content"`、不変 |
| 全面黒 | 純黒のみ | `reason="no_content"`、不変 |
| UI 部品の無視 | 白背景＋中央に大矩形＋隅に小さな黒矩形 | 小矩形が bbox に含まれない |
| 2 ページ並び | 白ガターで隔てた 2 つのカラー矩形 | 両方を含む外接矩形になる |
| 過剰トリミング防止 | 白背景の中央に 4×4 のみ | `reason="too_aggressive"`、不変 |
| 出力サイズ下限 | 極端に細い帯状コンテンツ | `reason="too_small"`、不変 |
| 例外処理 | `detect_content_bbox` を monkeypatch して送出 | `reason="error"`、不変、ログ出力あり |

既存 `tests/test_spread_splitter.py` には `trim_margins=True` を渡したときに 1 回目・2 回目の
トリミングが適用されることを確認するケースを追加する。

## 影響範囲

| 対象 | 影響 |
|------|------|
| `backend/margin_trimmer.py` | 新規 |
| `backend/spread_splitter.py` | `process_spread()` に引数追加、フロー 2 箇所追加 |
| `backend/job_manager.py` | `JobState` / `start_job` / `_run_job` のループ内処理 / `_process_spread_file` |
| `backend/requirements.txt` | `opencv-python` を追加 |
| `backend/main.py` | `StartJobRequest` に 1 フィールド追加 |
| `frontend/src/components/SettingsForm.tsx` | チェックボックス追加 |
| `frontend/src/App.tsx` | 状態追加・payload 追加 |
| `backend/tests/test_margin_trimmer.py` | 新規 |
| `backend/tests/test_spread_splitter.py` | ケース追加 |

### 出力ファイル名の非互換

顔面積比の定義が変わるため、ファイル名の `_N.Npct` の値が従来より大きくなる
（例: `2.6pct` → 約 `7.0pct`）。既存出力との数値の連続性は失われるが、これは意図した改善である。

**運用上の注意:** 面積比が正しく算出されるようになる結果、従来と同じ選別結果を得るには
**閾値を引き下げるのではなく引き上げる**方向で再調整する必要がある。

### 依存関係

`opencv-python` を新たに直接 import する。現在 `mediapipe` と `ultralytics` の依存として
`cv2 5.0.0` が venv に導入済みだが、直接依存となるため `backend/requirements.txt` に
`opencv-python` を明示的に追加する。
