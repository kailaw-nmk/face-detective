# Face Image Extractor — 仕様書

## 1. 概要

ブラウザUIから操作できるローカルWebアプリケーション。  
ユーザーが指定したフォルダ内の画像を再帰的に走査し、画像サイズに対して一定割合以上の顔が写っている画像のみを抽出（移動）して別フォルダに保存する。

---

## 2. ユーザー要件まとめ

| 項目 | 決定事項 |
|------|---------|
| 実行環境 | Windows ローカルPC |
| 利用者 | 1人（個人利用） |
| UIアクセス方法 | ブラウザ（localhost） |
| 入力フォルダ | ローカルパスまたは同一ネットワークのNAS（UNCパス `\\NAS\share\...`） |
| サブフォルダ | 再帰的に処理する |
| 対象フォーマット | JPEG, PNG, BMP, TIFF, WebP, HEIC/HEIF |
| 顔サイズ基準 | 画像面積に対する顔の面積比（%指定） |
| 複数顔の扱い | 最も大きい顔が基準を満たせば抽出対象とする |
| 保存方法 | 元画像を移動（元フォルダから削除される） |
| 保存先構造 | フラット（フォルダ階層なし、全ファイルを同一階層に並べる） |
| 進捗表示 | リアルタイムで処理状況を表示 |

---

## 3. システムアーキテクチャ

### 3.1 技術スタック

```
┌─────────────────────────────────────┐
│  Frontend (React + Vite)            │
│  - 設定フォーム                      │
│  - リアルタイム進捗表示（WebSocket）  │
│  - 処理結果サマリー                   │
├─────────────────────────────────────┤
│  Backend (Python FastAPI)           │
│  - REST API（設定受付・ジョブ管理）   │
│  - WebSocket（進捗配信）             │
│  - 顔検出エンジン（MediaPipe）       │
│  - ファイル操作（shutil）            │
└─────────────────────────────────────┘
```

### 3.2 選定理由

| 技術 | 理由 |
|------|------|
| **Python (FastAPI)** | 画像処理ライブラリ（MediaPipe, Pillow）との親和性が高い。非同期処理・WebSocket対応。 |
| **MediaPipe Face Detection** | Googleの高精度顔検出。OpenCVのHaar Cascadeより精度が高く、軽量。GPU不要。バウンディングボックスのサイズ取得が容易。 |
| **Pillow + pillow-heif** | 多フォーマット対応（HEIC含む）の画像読み込み |
| **React + Vite** | モダンなUI。リアルタイム更新との相性が良い |
| **WebSocket** | 進捗のリアルタイム配信に最適 |

---

## 4. 機能詳細

### 4.1 ブラウザUI画面

#### メイン画面（1画面構成）

**設定エリア：**

| フィールド | 入力方式 | バリデーション |
|-----------|---------|--------------|
| 入力フォルダパス | テキスト入力 | パスの存在チェック。ローカル（`C:\...`）とUNC（`\\NAS\...`）の両方を受け付ける |
| 顔サイズ割合（%） | 数値スライダー + 数値入力 | 1〜100の整数。デフォルト値: **5%** |
| 保存先フォルダパス | テキスト入力 | パスの存在チェック（存在しない場合は自動作成の確認を表示） |

**操作ボタン：**
- 「スキャン開始」ボタン — 処理を開始
- 「中止」ボタン — 処理を途中で中断（中断時点までの移動は維持）

**進捗表示エリア（リアルタイム更新）：**
- プログレスバー（処理済み / 全体ファイル数）
- 現在処理中のファイル名
- 経過時間
- ステータスカウンター：
  - スキャン済みファイル数
  - 顔検出成功（抽出対象）ファイル数
  - 顔未検出 / 基準未満でスキップしたファイル数
  - エラーファイル数（読み込み失敗等）

**結果サマリーエリア（処理完了後に表示）：**
- 合計処理ファイル数
- 抽出（移動）したファイル数
- スキップしたファイル数
- エラーファイル数（エラーリスト展開可能）
- 処理時間

### 4.2 顔検出ロジック

```
1. 画像を読み込む
2. 画像の面積を算出: image_area = width × height
3. MediaPipe Face Detection で顔を検出
4. 検出された全顔のバウンディングボックスから面積を算出
5. 最も大きい顔の面積を取得: max_face_area
6. 面積比を算出: ratio = (max_face_area / image_area) × 100
7. ratio ≥ ユーザー指定の閾値 → 抽出対象
```

### 4.3 ファイル操作

- **移動方式**: `shutil.move()` を使用
- **ファイル名重複時の処理**: 保存先に同名ファイルが既に存在する場合、`元のファイル名_連番.拡張子` のリネーム規則で保存（例: `photo_001.jpg`, `photo_002.jpg`）
- **保存先フォルダが存在しない場合**: 自動作成（`os.makedirs()`）

### 4.4 対応画像フォーマットと読み込み方法

| フォーマット | 拡張子 | 読み込みライブラリ |
|-------------|--------|------------------|
| JPEG | .jpg, .jpeg | Pillow |
| PNG | .png | Pillow |
| BMP | .bmp | Pillow |
| TIFF | .tif, .tiff | Pillow |
| WebP | .webp | Pillow |
| HEIC/HEIF | .heic, .heif | pillow-heif |

---

## 5. API設計

### 5.1 REST API

#### `POST /api/validate-path`
パスの存在確認。
```json
// Request
{ "path": "C:\\Users\\user\\Photos" }
// Response
{ "valid": true, "file_count": 1234 }
```

#### `POST /api/start`
処理ジョブの開始。
```json
// Request
{
  "input_path": "C:\\Users\\user\\Photos",
  "output_path": "C:\\Users\\user\\FacePhotos",
  "face_ratio_threshold": 5
}
// Response
{ "job_id": "uuid-xxxx", "status": "started" }
```

#### `POST /api/stop`
処理の中断。
```json
// Request
{ "job_id": "uuid-xxxx" }
// Response
{ "status": "stopped" }
```

#### `GET /api/status/{job_id}`
ジョブの現在状態を取得（WebSocket非対応時のフォールバック）。

### 5.2 WebSocket

#### `ws://localhost:8000/ws/{job_id}`
リアルタイム進捗配信。

```json
// 進捗メッセージ（処理中、1ファイルごとに送信）
{
  "type": "progress",
  "current_file": "subfolder\\photo.jpg",
  "processed": 150,
  "total": 1234,
  "extracted": 42,
  "skipped": 105,
  "errors": 3,
  "elapsed_seconds": 23.5
}

// 完了メッセージ
{
  "type": "complete",
  "summary": {
    "total_processed": 1234,
    "extracted": 312,
    "skipped": 910,
    "errors": 12,
    "elapsed_seconds": 180.2,
    "error_files": ["path/to/broken.heic", "..."]
  }
}

// エラーメッセージ
{
  "type": "error",
  "message": "入力フォルダにアクセスできません"
}
```

---

## 6. ディレクトリ構成

```
face-image-extractor/
├── backend/
│   ├── main.py              # FastAPI アプリケーション本体
│   ├── face_detector.py     # 顔検出ロジック（MediaPipe）
│   ├── file_scanner.py      # ファイル走査・フォーマット判定
│   ├── image_mover.py       # ファイル移動・リネーム処理
│   ├── job_manager.py       # ジョブ管理・進捗追跡
│   └── requirements.txt     # Python依存パッケージ
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # メインコンポーネント
│   │   ├── components/
│   │   │   ├── SettingsForm.jsx    # 設定フォーム
│   │   │   ├── ProgressPanel.jsx   # リアルタイム進捗表示
│   │   │   └── ResultSummary.jsx   # 結果サマリー
│   │   └── hooks/
│   │       └── useWebSocket.js     # WebSocket接続管理
│   ├── package.json
│   └── vite.config.js
├── start.bat                # Windows用一括起動スクリプト
└── README.md                # セットアップ手順・使い方
```

---

## 7. 起動方法

### `start.bat`（ワンクリック起動）

```bat
@echo off
echo Face Image Extractor を起動しています...

REM バックエンド起動
cd backend
start /B python -m uvicorn main:app --host 0.0.0.0 --port 8000
cd ..

REM フロントエンド起動
cd frontend
start /B npm run dev
cd ..

REM ブラウザを開く
timeout /t 3 >nul
start http://localhost:5173

echo 起動完了！ブラウザが開きます。
```

---

## 8. 非機能要件

| 項目 | 内容 |
|------|------|
| パフォーマンス | 画像1枚あたりの処理目標: 200ms以下（FHD画像基準） |
| エラーハンドリング | 個別ファイルのエラーは記録して次のファイルに進む。全体が止まらない設計。 |
| NASアクセス | UNCパス（`\\server\share`）をそのまま `pathlib.Path` で扱う。ネットワーク遅延を考慮し、ファイル読み込みにタイムアウト設定。 |
| ログ | バックエンドにファイルログ出力（`logs/` フォルダ）。デバッグ用途。 |
| セキュリティ | ローカル専用のためCORS設定は `localhost` のみ許可。認証なし。 |

---

## 9. 依存パッケージ

### Backend (Python 3.10+)
```
fastapi
uvicorn[standard]
websockets
mediapipe
Pillow
pillow-heif
```

### Frontend (Node.js 18+)
```
react
react-dom
vite
@vitejs/plugin-react
```

---

## 10. 今後の拡張候補（v1スコープ外）

- プレビュー機能: 抽出対象画像をブラウザ上でサムネイル表示し、移動前に確認
- 顔検出の信頼度（confidence）フィルター追加
- 処理履歴の保存・閲覧
- コピー/移動の選択式対応
- フォルダ構造維持オプション
- バッチスケジュール実行
