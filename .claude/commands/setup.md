プロジェクトの初期セットアップを実行してください。

## 手順

1. プロジェクトルートに `face-image-extractor/` ディレクトリを作成
2. Backend セットアップ:
   - `backend/` ディレクトリ作成
   - `python -m venv venv` で仮想環境作成
   - `requirements.txt` を作成し、依存パッケージを記載:
     ```
     fastapi
     uvicorn[standard]
     websockets
     mediapipe
     Pillow
     pillow-heif
     ruff
     pytest
     ```
   - `pip install -r requirements.txt` で依存インストール
   - `logs/` ディレクトリ作成

3. Frontend セットアップ:
   - `npm create vite@latest frontend -- --template react-ts`
   - `cd frontend && npm install`
   - `npm install -D tailwindcss @tailwindcss/vite`
   - Tailwind CSS の設定

4. `start.bat` を作成（バックエンド + フロントエンド同時起動）

5. 基本ファイルの雛形を作成:
   - `backend/main.py`（FastAPI + WebSocket骨格）
   - `frontend/src/App.tsx`（基本レイアウト）

6. `.gitignore` を作成（venv, node_modules, __pycache__, logs, .env）

セットアップ完了後、各コンポーネントが起動できることを確認してください。
