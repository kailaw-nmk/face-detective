開発サーバーを起動して動作確認を行ってください。

## 手順

1. バックエンド起動:
   - 仮想環境をアクティベート
   - `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
   - API docs が http://localhost:8000/docs でアクセスできることを確認

2. フロントエンド起動:
   - `cd frontend && npm run dev`
   - http://localhost:5173 でアクセスできることを確認

3. 基本動作確認:
   - ブラウザでフロントエンドが表示されること
   - バックエンドAPIにリクエストが通ること
   - WebSocket接続が確立されること

問題があれば報告し、修正してください。
