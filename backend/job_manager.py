"""ジョブ管理モジュール。

非同期タスクとして顔検出・画像コピー処理を実行し、
WebSocket 経由でリアルタイムに進捗を配信する。
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from face_detector import detect_faces, detect_faces_from_array
from file_scanner import scan_folder
from image_copier import copy_image, generate_dest_folder, save_spread_image
from person_detector import count_persons_split
from spread_splitter import process_spread

logger = logging.getLogger(__name__)


class JobState:
    """単一ジョブの状態を保持するクラス。"""

    def __init__(
        self,
        job_id: str,
        source_folder: Path,
        dest_folder: Path,
        threshold: float,
        spread_split: bool = False,
        require_both_eyes: bool = False,
        min_eye_ratio: float = 0.25,
        min_face_score: float = 0.5,
        yolo_confidence: float = 0.2,
    ) -> None:
        """ジョブ状態を初期化する。

        Args:
            job_id: ジョブの一意識別子。
            source_folder: 走査対象フォルダ。
            dest_folder: 画像移動先フォルダ。
            threshold: 顔面積比の閾値 (%)。
            spread_split: 見開き分割を有効にするかどうか。
            require_both_eyes: 両目が映っている画像のみ抽出するかどうか。
            min_eye_ratio: 両目間距離 / 顔幅 の最小比率。
            min_face_score: 両目判定に必要な最低検出信頼度。
            yolo_confidence: YOLO 人物検出の信頼度閾値。
        """
        self.job_id = job_id
        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.threshold = threshold
        self.spread_split = spread_split
        self.require_both_eyes = require_both_eyes
        self.min_eye_ratio = min_eye_ratio
        self.min_face_score = min_face_score
        self.yolo_confidence = yolo_confidence

        self.status: str = "running"
        self.total: int = 0
        self.processed: int = 0
        self.extracted: int = 0
        self.skipped: int = 0
        self.errors: int = 0
        self.split_count: int = 0
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
            "split_count": self.split_count,
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
        spread_split: bool = False,
        require_both_eyes: bool = False,
        min_eye_ratio: float = 0.25,
        min_face_score: float = 0.5,
        yolo_confidence: float = 0.2,
    ) -> tuple[str, str]:
        """ジョブをペンディング状態で登録し、(job_id, dest_folder) を返す。

        Args:
            source_folder: 走査対象フォルダのパス文字列。
            threshold: 顔面積比の閾値 (%)。
            spread_split: 見開き分割を有効にするかどうか。
            require_both_eyes: 両目が映っている画像のみ抽出するかどうか。
            min_eye_ratio: 両目間距離 / 顔幅 の最小比率。
            min_face_score: 両目判定に必要な最低検出信頼度。
            yolo_confidence: YOLO 人物検出の信頼度閾値。

        Returns:
            登録されたジョブ ID 文字列と、自動生成された保存先フォルダパス文字列のタプル。
        """
        job_id = str(uuid.uuid4())
        dest_folder = str(generate_dest_folder(Path(source_folder)))
        self._pending[job_id] = {
            "source_folder": source_folder,
            "dest_folder": dest_folder,
            "threshold": threshold,
            "spread_split": spread_split,
            "require_both_eyes": require_both_eyes,
            "min_eye_ratio": min_eye_ratio,
            "min_face_score": min_face_score,
            "yolo_confidence": yolo_confidence,
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
        spread_split: bool = False,
        require_both_eyes: bool = False,
        min_eye_ratio: float = 0.25,
        min_face_score: float = 0.5,
        yolo_confidence: float = 0.2,
    ) -> str:
        """新規ジョブを作成して非同期タスクとして起動する。

        Args:
            source_folder: 走査対象フォルダのパス文字列。
            dest_folder: 画像移動先フォルダのパス文字列。
            threshold: 顔面積比の閾値 (%)。
            send_message: WebSocket へメッセージを送信するコルーチン関数。
            job_id: 使用するジョブ ID。None の場合は新規 UUID を生成する。
            spread_split: 見開き分割を有効にするかどうか。
            require_both_eyes: 両目が映っている画像のみ抽出するかどうか。
            min_eye_ratio: 両目間距離 / 顔幅 の最小比率。
            min_face_score: 両目判定に必要な最低検出信頼度。
            yolo_confidence: YOLO 人物検出の信頼度閾値。

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
            spread_split=spread_split,
            require_both_eyes=require_both_eyes,
            min_eye_ratio=min_eye_ratio,
            min_face_score=min_face_score,
            yolo_confidence=yolo_confidence,
        )
        self._jobs[job_id] = state
        logger.info("ジョブを開始します: job_id=%s, spread_split=%s", job_id, spread_split)

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
                if state.spread_split:
                    self._process_spread_file(state, file_path)
                else:
                    result = detect_faces(
                        file_path, state.threshold,
                        min_eye_ratio=state.min_eye_ratio,
                        min_face_score=state.min_face_score,
                    )

                    if result["should_move"] and (
                        not state.require_both_eyes
                        or result["both_eyes_visible"]
                    ):
                        copy_image(
                            file_path, state.source_folder, state.dest_folder,
                            face_ratio=result["max_face_ratio"],
                            both_eyes_visible=result["both_eyes_visible"],
                        )
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
                    "split_count": state.split_count,
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
                "split_count": state.split_count,
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
            "ジョブ完了: job_id=%s, 合計=%d, 抽出=%d, スキップ=%d, 分割=%d, エラー=%d",
            state.job_id,
            state.total,
            state.extracted,
            state.skipped,
            state.split_count,
            state.errors,
        )

    def _process_spread_file(self, state: JobState, file_path: Path) -> None:
        """人物検出で見開き分割を行い、各画像に顔検出・コピーを適用する。

        Args:
            state: 実行中のジョブ状態オブジェクト。
            file_path: 処理対象の画像ファイルパス。
        """
        import numpy as np

        def _count_fn(arr: np.ndarray) -> int:
            return count_persons_split(arr, confidence=state.yolo_confidence)

        spread_result = process_spread(file_path, _count_fn)

        if spread_result["action"] == "split":
            state.split_count += 1

        for img, suffix in zip(spread_result["images"], spread_result["suffixes"]):
            # 各画像（分割後 or 非分割）で顔検出して閾値判定する
            image_array = np.array(img, dtype=np.uint8)
            face_result = detect_faces_from_array(
                image_array, img.width, img.height, state.threshold,
                min_eye_ratio=state.min_eye_ratio,
                min_face_score=state.min_face_score,
            )

            if face_result["should_move"] and (
                not state.require_both_eyes
                or face_result["both_eyes_visible"]
            ):
                save_spread_image(
                    img, file_path, suffix,
                    state.source_folder, state.dest_folder,
                    face_ratio=face_result["max_face_ratio"],
                    both_eyes_visible=face_result["both_eyes_visible"],
                )
                state.extracted += 1
            else:
                state.skipped += 1
