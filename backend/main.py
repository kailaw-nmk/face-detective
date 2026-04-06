"""Face Image Extractor バックエンド — FastAPI アプリケーション本体。

REST API エンドポイントと WebSocket によるリアルタイム進捗配信を提供する。
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from file_scanner import scan_folder
from job_manager import JobManager

# ---------------------------------------------------------------------------
# ロギング設定
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).parent / "logs"
os.makedirs(_LOG_DIR, exist_ok=True)

_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)

_file_handler = RotatingFileHandler(
    _LOG_DIR / "app.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_formatter)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_file_handler, _console_handler],
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI アプリケーション
# ---------------------------------------------------------------------------

app = FastAPI(title="Face Image Extractor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:52841"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

job_manager = JobManager()

# ---------------------------------------------------------------------------
# リクエスト / レスポンスモデル
# ---------------------------------------------------------------------------


class ValidatePathRequest(BaseModel):
    """パス検証リクエストのモデル。"""

    path: str


class ValidatePathResponse(BaseModel):
    """パス検証レスポンスのモデル。"""

    valid: bool
    image_count: int
    message: str


class StartJobRequest(BaseModel):
    """ジョブ開始リクエストのモデル。"""

    source_folder: str
    threshold: float
    spread_split: bool = False
    require_both_eyes: bool = False
    min_eye_ratio: float = 0.25
    min_face_score: float = 0.5
    yolo_confidence: float = 0.2


class StartJobResponse(BaseModel):
    """ジョブ開始レスポンスのモデル。"""

    job_id: str
    dest_folder: str


class StopJobRequest(BaseModel):
    """ジョブ停止リクエストのモデル。"""

    job_id: str


class StopJobResponse(BaseModel):
    """ジョブ停止レスポンスのモデル。"""

    success: bool


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------


@app.post("/api/validate-path", response_model=ValidatePathResponse)
async def validate_path(request: ValidatePathRequest) -> ValidatePathResponse:
    """指定パスの存在確認と画像ファイル件数を返す。

    Args:
        request: パス検証リクエスト。

    Returns:
        有効フラグ、画像件数、メッセージを含むレスポンス。
    """
    folder = Path(request.path)
    logger.info("パス検証リクエスト: %s", folder)

    if not folder.exists():
        return ValidatePathResponse(
            valid=False,
            image_count=0,
            message="指定されたパスが存在しません。",
        )

    if not folder.is_dir():
        return ValidatePathResponse(
            valid=False,
            image_count=0,
            message="指定されたパスはディレクトリではありません。",
        )

    try:
        image_files = scan_folder(folder)
        count = len(image_files)
        return ValidatePathResponse(
            valid=True,
            image_count=count,
            message=f"{count} 件の画像ファイルが見つかりました。",
        )
    except Exception as exc:
        logger.error("パス検証中にエラーが発生しました: %s", exc, exc_info=True)
        return ValidatePathResponse(
            valid=False,
            image_count=0,
            message=f"スキャン中にエラーが発生しました: {exc}",
        )


@app.post("/api/start", response_model=StartJobResponse)
async def start_job(request: StartJobRequest) -> StartJobResponse:
    """顔検出・画像コピージョブをペンディング状態で登録する。

    保存先フォルダは source_folder から自動生成される（末尾に ``_face`` を付与）。
    クライアントは返却された job_id を使って WebSocket ``/ws/{job_id}`` に
    接続することでジョブを実際に開始できる。

    Args:
        request: ジョブ開始リクエスト（source_folder, threshold）。

    Returns:
        生成されたジョブ ID と自動生成された保存先フォルダパス。
    """
    job_id, dest_folder = job_manager.register_job(
        source_folder=request.source_folder,
        threshold=request.threshold,
        spread_split=request.spread_split,
        require_both_eyes=request.require_both_eyes,
        min_eye_ratio=request.min_eye_ratio,
        min_face_score=request.min_face_score,
        yolo_confidence=request.yolo_confidence,
    )
    logger.info(
        "ジョブ登録: job_id=%s, src=%s, dest=%s, threshold=%.1f, spread_split=%s",
        job_id,
        request.source_folder,
        dest_folder,
        request.threshold,
        request.spread_split,
    )
    return StartJobResponse(job_id=job_id, dest_folder=dest_folder)


@app.post("/api/stop", response_model=StopJobResponse)
async def stop_job(request: StopJobRequest) -> StopJobResponse:
    """実行中のジョブを停止（キャンセル）する。

    Args:
        request: 停止対象のジョブ ID を含むリクエスト。

    Returns:
        キャンセル受け付けの成否。
    """
    success = job_manager.stop_job(request.job_id)
    logger.info("ジョブ停止要求: job_id=%s, success=%s", request.job_id, success)
    return StopJobResponse(success=success)


@app.get("/api/status/{job_id}")
async def get_status(job_id: str) -> dict:
    """ジョブの現在状態を返す。

    Args:
        job_id: 状態を取得するジョブの ID。

    Returns:
        ジョブ状態の辞書。ジョブが存在しない場合は not_found ステータスを返す。
    """
    status = job_manager.get_status(job_id)
    if status is None:
        return {"job_id": job_id, "status": "not_found"}
    return status


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str) -> None:
    """WebSocket 接続を受け付け、ジョブの進捗をリアルタイムに配信する。

    クライアントが接続した時点でペンディングジョブを開始し、完了またはキャンセルまで
    進捗メッセージを送信し続ける。

    Args:
        websocket: WebSocket 接続オブジェクト。
        job_id: 事前に ``POST /api/start`` で登録したジョブの ID。
    """
    import json

    await websocket.accept()
    logger.info("WebSocket 接続: job_id=%s", job_id)

    pending = job_manager._pending.pop(job_id, None)
    if pending is None:
        await websocket.send_text(
            json.dumps(
                {"type": "error", "message": "ジョブが見つかりません。"},
                ensure_ascii=False,
            )
        )
        await websocket.close()
        return

    async def send_message(message: str) -> None:
        """WebSocket へテキストメッセージを送信するコルーチン。

        Args:
            message: 送信する JSON 文字列。
        """
        await websocket.send_text(message)

    await job_manager.start_job(
        source_folder=pending["source_folder"],
        dest_folder=pending["dest_folder"],
        threshold=pending["threshold"],
        send_message=send_message,
        job_id=job_id,
        spread_split=pending.get("spread_split", False),
        require_both_eyes=pending.get("require_both_eyes", False),
        min_eye_ratio=pending.get("min_eye_ratio", 0.25),
        min_face_score=pending.get("min_face_score", 0.5),
        yolo_confidence=pending.get("yolo_confidence", 0.2),
    )

    logger.info("ジョブ実行開始: job_id=%s", job_id)

    try:
        while True:
            status = job_manager.get_status(job_id)
            if status and status.get("status") in ("complete", "cancelled", "error"):
                break
            try:
                data = await websocket.receive_text()
                logger.debug("クライアントからメッセージ受信: %s", data)
            except WebSocketDisconnect:
                logger.info("WebSocket 切断 (処理中): job_id=%s", job_id)
                job_manager.stop_job(job_id)
                return
    except WebSocketDisconnect:
        logger.info("WebSocket 切断: job_id=%s", job_id)
        job_manager.stop_job(job_id)
    except Exception as exc:
        logger.error("WebSocket エラー: %s", exc, exc_info=True)
    finally:
        logger.info("WebSocket セッション終了: job_id=%s", job_id)
