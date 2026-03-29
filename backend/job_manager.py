"""ジョブ管理モジュール。

非同期タスクとして顔検出・画像コピー処理を実行し、
WebSocket 経由でリアルタイムに進捗を配信する。
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from face_detector import detect_faces
from file_scanner import scan_folder
from image_copier import copy_image, generate_dest_folder

logger = logging.getLogger(__name__)


class JobState:
    """単一ジョブの状態を保持するクラス。"""

    def __init__(
        self,
        job_id: str,
        source_folder: Path,
        dest_folder: Path,
        threshold: float,
    ) -> None:
        """ジョブ状態を初期化する。

        Args:
            job_id: ジョブの一意識別子。
            source_folder: 走査対象フォルダ。
            dest_folder: 画像移動先フォルダ。
            threshold: 顔面積比の閾値 (%)。
        """
        self.job_id = job_id
        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.threshold = threshold

        self.status: str = "running"
        self.total: int = 0
        self.processed: int = 0
        self.extracted: int = 0
        self.skipped: int = 0
        self.errors: int = 0
        self.error_files: list[str] = []
        self.current_file: str = ""
        self.cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        """ジョブ状態を辞書形式で返す。

        Returns:
            ジョブ状態を表す辞書。
        """
        return {
            "job_id": self.job_id,
            "status": self.status,
            "total": self.total,
            "processed": self.processed,
            "extracted": self.extracted,
            "skipped": self.skipped,
            "errors": self.errors,
            "error_files": self.error_files,
            "current_file": self.current_file,
        }


class JobManager:
    """ジョブの作成・管理・進捗配信を行うクラス。"""

    def __init__(self) -> None:
        """JobManager を初期化する。"""
        self._jobs: dict[str, JobState] = {}
        self._pending: dict[str, dict[str, Any]] = {}

    def register_job(
        self,
        source_folder: str,
        threshold: float,
    ) -> tuple[str, str]:
        """ジョブをペンディング状態で登録し、(job_id, dest_folder) を返す。

        保存先フォルダは source_folder から自動生成する（末尾に ``_face`` を付与）。
        WebSocket 接続前にクライアントへ job_id と dest_folder を渡すための事前登録。

        Args:
            source_folder: 走査対象フォルダのパス文字列。
            threshold: 顔面積比の閾値 (%)。

        Returns:
            登録されたジョブ ID 文字列と、自動生成された保存先フォルダパス文字列のタプル。
        """
        job_id = str(uuid.uuid4())
        dest_folder = str(generate_dest_folder(Path(source_folder)))
        self._pending[job_id] = {
            "source_folder": source_folder,
            "dest_folder": dest_folder,
            "threshold": threshold,
        }
        logger.info("ジョブを登録しました (pending): job_id=%s", job_id)
        return job_id, dest_folder

    async def start_job(
        self,
        source_folder: str,
        dest_folder: str,
        threshold: float,
        send_message: Any,
        job_id: str | None = None,
    ) -> str:
        """新規ジョブを作成して非同期タスクとして起動する。

        Args:
            source_folder: 走査対象フォルダのパス文字列。
            dest_folder: 画像移動先フォルダのパス文字列。
            threshold: 顔面積比の閾値 (%)。
            send_message: WebSocket へメッセージを送信するコルーチン関数。
                          引数として JSON 文字列を受け取る。
            job_id: 使用するジョブ ID。None の場合は新規 UUID を生成する。

        Returns:
            ジョブ ID 文字列。
        """
        if job_id is None:
            job_id = str(uuid.uuid4())
        state = JobState(
            job_id=job_id,
            source_folder=Path(source_folder),
            dest_folder=Path(dest_folder),
            threshold=threshold,
        )
        self._jobs[job_id] = state
        logger.info("ジョブを開始します: job_id=%s", job_id)

        asyncio.create_task(self._run_job(state, send_message))
        return job_id

    def stop_job(self, job_id: str) -> bool:
        """指定ジョブのキャンセルフラグを立てる。

        Args:
            job_id: キャンセルするジョブの ID。

        Returns:
            ジョブが存在してキャンセル要求を受け付けた場合 True、
            ジョブが存在しない場合 False。
        """
        state = self._jobs.get(job_id)
        if state is None:
            logger.warning("存在しないジョブのキャンセルを要求されました: %s", job_id)
            return False
        state.cancelled = True
        logger.info("ジョブのキャンセルを要求しました: job_id=%s", job_id)
        return True

    def get_status(self, job_id: str) -> dict[str, Any] | None:
        """指定ジョブの現在状態を返す。

        Args:
            job_id: 状態を取得するジョブの ID。

        Returns:
            ジョブ状態の辞書。ジョブが存在しない場合は None。
        """
        state = self._jobs.get(job_id)
        if state is None:
            return None
        return state.to_dict()

    async def _run_job(self, state: JobState, send_message: Any) -> None:
        """ジョブの実行本体。ファイルスキャン・顔検出・コピー処理を行う。

        処理中は WebSocket 経由で進捗メッセージを送信する。
        個別ファイルのエラーはログに記録して処理を継続する。

        Args:
            state: 実行対象のジョブ状態オブジェクト。
            send_message: WebSocket へ JSON メッセージを送るコルーチン関数。
        """
        import json

        try:
            image_files = scan_folder(state.source_folder)
        except Exception as exc:
            logger.error(
                "フォルダのスキャンに失敗しました: %s — %s",
                state.source_folder,
                exc,
                exc_info=True,
            )
            state.status = "error"
            error_msg = json.dumps(
                {"type": "error", "message": f"フォルダのスキャンに失敗しました: {exc}"},
                ensure_ascii=False,
            )
            await send_message(error_msg)
            return

        state.total = len(image_files)
        logger.info(
            "ジョブ %s: 対象ファイル数 = %d", state.job_id, state.total
        )

        for file_path in image_files:
            if state.cancelled:
                logger.info("ジョブがキャンセルされました: %s", state.job_id)
                state.status = "cancelled"
                break

            state.current_file = str(file_path)

            try:
                result = detect_faces(file_path, state.threshold)

                if result["should_move"]:
                    copy_image(file_path, state.source_folder, state.dest_folder)
                    state.extracted += 1
                else:
                    state.skipped += 1

            except Exception as exc:
                logger.error(
                    "ファイル処理中にエラーが発生しました: %s — %s",
                    file_path,
                    exc,
                    exc_info=True,
                )
                state.errors += 1
                state.error_files.append(str(file_path))

            finally:
                state.processed += 1

            progress_msg = json.dumps(
                {
                    "type": "progress",
                    "current_file": state.current_file,
                    "processed": state.processed,
                    "total": state.total,
                    "extracted": state.extracted,
                    "skipped": state.skipped,
                    "errors": state.errors,
                },
                ensure_ascii=False,
            )
            try:
                await send_message(progress_msg)
            except Exception as ws_exc:
                logger.warning(
                    "WebSocket へのメッセージ送信に失敗しました: %s", ws_exc
                )

            await asyncio.sleep(0)

        if state.status == "running":
            state.status = "complete"

        complete_msg = json.dumps(
            {
                "type": "complete",
                "total": state.total,
                "extracted": state.extracted,
                "skipped": state.skipped,
                "errors": state.errors,
                "error_files": state.error_files,
            },
            ensure_ascii=False,
        )
        try:
            await send_message(complete_msg)
        except Exception as ws_exc:
            logger.warning(
                "完了メッセージの送信に失敗しました: %s", ws_exc
            )

        logger.info(
            "ジョブ完了: job_id=%s, 合計=%d, 抽出=%d, スキップ=%d, エラー=%d",
            state.job_id,
            state.total,
            state.extracted,
            state.skipped,
            state.errors,
        )
