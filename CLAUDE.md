# Face Image Extractor - プロジェクト指示書

## プロジェクト概要
ブラウザUIから操作するローカルWebアプリ。指定フォルダ内の画像を再帰走査し、画像面積に対して一定割合以上の顔が写っている画像を別フォルダに移動する。

## アーキテクチャ
- **Backend**: Python 3.10+ / FastAPI / uvicorn
- **Frontend**: React + Vite (TypeScript)
- **顔検出**: MediaPipe Face Detection
- **画像処理**: Pillow + pillow-heif
- **リアルタイム通信**: WebSocket（FastAPI native）

## ディレクトリ構成
```
face-image-extractor/
├── backend/
│   ├── main.py              # FastAPI アプリ本体 + WebSocket
│   ├── face_detector.py     # MediaPipe顔検出ロジック
│   ├── file_scanner.py      # ファイル再帰走査・フォーマット判定
│   ├── image_mover.py       # ファイル移動・リネーム
│   ├── job_manager.py       # ジョブ管理・進捗追跡
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── SettingsForm.tsx
│   │   │   ├── ProgressPanel.tsx
│   │   │   └── ResultSummary.tsx
│   │   └── hooks/
│   │       └── useWebSocket.ts
│   ├── package.json
│   └── vite.config.ts
├── start.bat
└── README.md
```

## 技術的制約・ルール

### 全般
- OS: Windows 環境で動作すること（パスは `\` 区切り、UNCパス `\\NAS\...` 対応）
- パスの扱いは `pathlib.Path` を使い、OS差を吸収する
- 個人利用のためセキュリティは最小限（localhost限定CORS、認証なし）
- 日本語UIとする

### Backend
- Python仮想環境(venv)を使用する
- 非同期処理は `asyncio` + `FastAPI BackgroundTasks` または `asyncio.create_task`
- 個別ファイルのエラーはログに記録して次に進む（全体を止めない）
- NASアクセス時のタイムアウトを考慮する
- ログは `logging` モジュールで `logs/` フォルダに出力

### Frontend
- TypeScriptを使用する
- UIライブラリは使わず、Tailwind CSSでスタイリング
- WebSocket接続はカスタムhookで管理
- 状態管理はReactのuseState/useReducerで十分（Redux不要）

### 顔検出ロジック
1. 画像読み込み → Pillow（HEIC は pillow-heif でプラグイン登録）
2. MediaPipe Face Detection でバウンディングボックス取得
3. 面積比 = (最大顔面積 / 画像面積) × 100
4. 面積比 ≥ 閾値 → 移動対象

### 対応フォーマット
`.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.webp`, `.heic`, `.heif`

### ファイル移動ルール
- `shutil.move()` を使用
- 保存先はフラット（階層なし）
- ファイル名重複時: `{stem}_{連番}.{ext}` でリネーム（例: `photo_001.jpg`）

## コーディング規約
- Pythonは PEP 8 に従う（ruff でリント）
- TypeScriptは ESLint + Prettier
- 関数には docstring / JSDoc を付ける
- コミットメッセージは日本語OK、`feat:`, `fix:`, `docs:` プレフィックス使用

## テスト方針
- Backend: pytest で主要ロジック（顔検出、ファイル操作、リネーム）をテスト
- Frontend: 手動テストで十分（個人利用のため）
- テスト用の画像サンプルは `tests/fixtures/` に配置
