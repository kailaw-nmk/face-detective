# Face Image Extractor — Claude Code 設定パッケージ

## 概要
このZIPには、Face Image Extractorプロジェクトを Claude Code で効率的に開発するための設定ファイル一式が含まれています。

## ファイル構成

```
face-image-extractor-config/
├── CLAUDE.md                      # プロジェクト指示書（自動読み込み）
├── .mcp.json                      # プロジェクト用MCP設定
├── .claude/
│   ├── settings.json              # パーミッション設定
│   ├── agents/
│   │   ├── backend-dev.md         # バックエンド専門エージェント
│   │   ├── frontend-dev.md        # フロントエンド専門エージェント
│   │   └── qa-tester.md           # QAテスト専門エージェント
│   └── commands/
│       ├── setup.md               # /setup — プロジェクト初期セットアップ
│       ├── test.md                # /test — テスト実行
│       └── dev.md                 # /dev — 開発サーバー起動
└── README.md                      # このファイル
```

## セットアップ手順

### 1. プロジェクトフォルダを作成
```powershell
mkdir C:\AI-dev\face-image-extractor
cd C:\AI-dev\face-image-extractor
git init
```

### 2. ZIPを展開して配置
ZIPの中身を `C:\AI-dev\face-image-extractor\` の直下に展開してください。

```
C:\AI-dev\face-image-extractor\
├── CLAUDE.md              ← ここに配置
├── .mcp.json              ← ここに配置
├── .claude\               ← ここに配置
│   ├── settings.json
│   ├── agents\
│   └── commands\
└── (ここに backend/, frontend/ が作られる)
```

### 3. グローバル設定の確認
既存のグローバルMCP設定（`~/.claude.json`）はそのまま使えます。
プロジェクト用の `.mcp.json` には、このプロジェクトに特に有用な3つのMCPサーバーのみを設定しています：

| MCP | 用途 |
|-----|------|
| **Context7** | ライブラリのドキュメント参照（FastAPI, MediaPipe, React等） |
| **Sequential Thinking** | 複雑なロジック設計時の段階的思考 |
| **Playwright** | ブラウザUIの自動テスト |

### 4. Claude Codeを起動
```powershell
cd C:\AI-dev\face-image-extractor
claude
```

### 5. 初期セットアップを実行
Claude Code内で以下のコマンドを実行：
```
/setup
```
これにより、Backend（Python venv + 依存）、Frontend（Vite + React + Tailwind）、起動スクリプトが自動作成されます。

## カスタムコマンド一覧

| コマンド | 説明 |
|---------|------|
| `/setup` | プロジェクトの初期セットアップ（venv作成、npm install、雛形ファイル生成） |
| `/test` | pytest実行 + ruffリントチェック |
| `/dev` | 開発サーバー起動（バックエンド + フロントエンド） |

## カスタムエージェント一覧

| エージェント | 色 | 用途 |
|-------------|-----|------|
| **backend-dev** | 🔵 青 | Python/FastAPI/MediaPipe のバックエンド開発 |
| **frontend-dev** | 🟢 緑 | React/TypeScript/Tailwind のフロントエンド開発 |
| **qa-tester** | 🔴 赤 | テスト実行・エッジケース検証・品質保証 |

Claude Codeが自動的にタスク内容に応じて適切なエージェントに委譲します。

## 開発の進め方（推奨）

### Phase 1: 基盤構築
```
/setup を実行してプロジェクト雛形を作成
```

### Phase 2: バックエンド実装
```
以下を順番に実装してください：
1. file_scanner.py — 再帰ファイル走査
2. face_detector.py — MediaPipe顔検出
3. image_mover.py — ファイル移動・リネーム
4. job_manager.py — ジョブ管理
5. main.py — API + WebSocketエンドポイント
各モジュールのpytestテストも作成してください。
```

### Phase 3: フロントエンド実装
```
フロントエンドUIを実装してください：
1. SettingsForm — 設定入力フォーム
2. ProgressPanel — リアルタイム進捗表示
3. ResultSummary — 結果サマリー
4. useWebSocket — WebSocket通信hook
5. App.tsx — 全体統合
```

### Phase 4: 結合テスト
```
/test を実行し、続けてブラウザで /dev で起動した画面を確認してください。
実際のテスト画像フォルダで end-to-end テストを行ってください。
```

## MCP設定のカスタマイズ

`.mcp.json` に追加のMCPサーバーを設定できます。  
グローバル設定（`~/.claude.json`）に既にあるサーバー（browsermcp, github等）は  
プロジェクト内でも自動的に利用可能です。

## 注意事項

- `Context7` の API キーは提供ファイル内のものをそのまま使用しています。必要に応じて差し替えてください。
- `.claude/settings.json` のパーミッション設定は開発効率を優先しています。本番環境向けにはより制限的にしてください。

## Tailscale 経由でのアクセス

```
https://i3-2060.tail673a53.ts.net:8443/face-detect/
```

OtaGenX の Tailscale Serve が `:8443` の `/face-detect` を
`http://127.0.0.1:52840` にパスマウントしている（`tailscale serve status` で確認できる）。
backend が `frontend/dist` を配信するため、`http://localhost:52840/` と
上記 URL の両方から同じ画面が開く。

### ビルド

```powershell
cd frontend
npm run build
```

`build` スクリプトは `--base=/face-detect/` を渡すので、**素で実行して問題ない**。

このプレフィックスが無い dist は `/assets/...` を参照するため、
`http://localhost:52840/` では動くのに Tailscale 経由だけ画面が真っ白になる。
localhost だけ見ていると気付けないので、既定を安全側に倒してある。
取り違えても気付けるよう、backend は起動時に `frontend/dist/index.html` を検査し、
プレフィックスが無ければ警告をログに出す。

`start.bat` はサーバー起動前に必ずこのビルドを実行する。ビルドが失敗した場合は
古い dist を配信しないよう、サーバーを起動せずに終了する。

**フロントを変更したら再ビルドが必要**（`start.bat` を再実行するのが確実）。
`npm run dev` (`:52841`) はホットリロードで動くが、Tailscale 経由が配信するのは
dev サーバーではなく `frontend/dist` である点に注意。

`frontend/dist` は `.gitignore` によりコミット対象外のため、デプロイ先で再ビルドが必要。
