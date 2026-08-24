"""job_manager の処理済みスキップに関するテスト。

顔検出は重い外部依存のためモックし、スキャン結果のフィルタリングと
処理済み記録の書き込みのみを検証する。
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

import job_manager as job_manager_module
from job_manager import JobManager, JobState
from processed_index import PROCESSED_DIR_NAME


def _make_source(tmp_path: Path, count: int) -> tuple[Path, Path]:
    """入力フォルダに画像を作り、(入力, 保存先) を返す。

    Args:
        tmp_path: pytest の一時ディレクトリ。
        count: 生成する画像の枚数。

    Returns:
        (source_folder, dest_folder) のタプル。保存先は未作成のまま返す。
    """
    source = tmp_path / "src"
    source.mkdir()
    for i in range(count):
        Image.new("RGB", (40, 40), color=(i * 10 % 256, 100, 150)).save(
            source / f"photo_{i:03d}.png"
        )
    return source, tmp_path / "src_face"


def _make_state(
    source: Path,
    dest: Path,
    *,
    skip_processed: bool,
    threshold: float = 5.0,
) -> JobState:
    """テスト用の JobState を組み立てる。

    Args:
        source: 走査対象フォルダ。
        dest: 保存先フォルダ。
        skip_processed: 処理済みスキップを有効にするかどうか。
        threshold: 顔面積比の閾値 (%)。設定ハッシュの違いを作るのに使う。

    Returns:
        構築した JobState。
    """
    return JobState(
        job_id="test-job",
        source_folder=source,
        dest_folder=dest,
        threshold=threshold,
        skip_processed=skip_processed,
    )


def _patch_face_detection(
    monkeypatch: pytest.MonkeyPatch, *, should_move: bool = True
) -> None:
    """顔検出を固定結果を返すモックに差し替える。

    Args:
        monkeypatch: pytest の monkeypatch フィクスチャ。
        should_move: 抽出対象と判定させるかどうか。
    """
    result = {
        "should_move": should_move,
        "max_face_ratio": 10.0,
        "both_eyes_visible": True,
    }
    monkeypatch.setattr(
        job_manager_module, "detect_faces", MagicMock(return_value=result)
    )
    monkeypatch.setattr(
        job_manager_module, "detect_faces_from_array", MagicMock(return_value=result)
    )


def _run(state: JobState) -> list[str]:
    """ジョブを最後まで実行し、送信されたメッセージ列を返す。

    Args:
        state: 実行対象のジョブ状態。

    Returns:
        WebSocket へ送られた JSON 文字列のリスト。
    """
    messages: list[str] = []

    async def _send(message: str) -> None:
        messages.append(message)

    asyncio.run(JobManager()._run_job(state, _send))
    return messages


class TestJobStateSkipProcessed:
    """JobState の処理済みスキップ用フィールドのテストクラス。"""

    def test_defaults_to_disabled(self, tmp_path: Path) -> None:
        """skip_processed を省略すると False で、カウンタが 0 であること。"""
        state = JobState(
            job_id="j",
            source_folder=tmp_path,
            dest_folder=tmp_path,
            threshold=5.0,
        )

        assert state.skip_processed is False
        assert state.already_processed == 0

    def test_to_dict_includes_already_processed(self, tmp_path: Path) -> None:
        """to_dict に already_processed が含まれること。

        欠けると /api/status の利用側で件数を表示できない。
        """
        state = JobState(
            job_id="j",
            source_folder=tmp_path,
            dest_folder=tmp_path,
            threshold=5.0,
        )

        assert "already_processed" in state.to_dict()

    def test_register_job_stores_flag(self, tmp_path: Path) -> None:
        """register_job が skip_processed を pending に保持すること。"""
        source = tmp_path / "src"
        source.mkdir()
        manager = JobManager()

        job_id, _dest = manager.register_job(
            source_folder=str(source),
            threshold=5.0,
            skip_processed=True,
        )

        assert manager._pending[job_id]["skip_processed"] is True


class TestRunJobSkipProcessed:
    """ジョブ全体での処理済みスキップのテストクラス。"""

    def test_second_run_skips_everything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同じ設定で 2 回実行すると 2 回目は 1 件も処理しないこと。"""
        _patch_face_detection(monkeypatch)
        source, dest = _make_source(tmp_path, 3)
        _run(_make_state(source, dest, skip_processed=True))

        second = _make_state(source, dest, skip_processed=True)
        _run(second)

        assert second.total == 0
        assert second.processed == 0
        assert second.already_processed == 3

    def test_second_run_processes_only_new_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1 回目のあとに追加された画像だけが 2 回目で処理されること。"""
        _patch_face_detection(monkeypatch)
        source, dest = _make_source(tmp_path, 2)
        _run(_make_state(source, dest, skip_processed=True))
        Image.new("RGB", (40, 40), color=(9, 9, 9)).save(source / "new.png")

        second = _make_state(source, dest, skip_processed=True)
        _run(second)

        assert second.total == 1
        assert second.already_processed == 2

    def test_disabled_flag_reprocesses_everything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """skip_processed が無効なら記録があっても全件処理すること。"""
        _patch_face_detection(monkeypatch)
        source, dest = _make_source(tmp_path, 3)
        _run(_make_state(source, dest, skip_processed=True))

        second = _make_state(source, dest, skip_processed=False)
        _run(second)

        assert second.total == 3
        assert second.already_processed == 0

    def test_changed_settings_reprocess_everything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """閾値を変えると記録が分かれ、全件が再処理されること。

        閾値を下げたのに前回スキップされた画像を拾えない、という
        直感に反する挙動を防ぐための保証。
        """
        _patch_face_detection(monkeypatch)
        source, dest = _make_source(tmp_path, 3)
        _run(_make_state(source, dest, skip_processed=True, threshold=5.0))

        second = _make_state(source, dest, skip_processed=True, threshold=20.0)
        _run(second)

        assert second.total == 3
        assert second.already_processed == 0

    def test_skipped_images_are_recorded_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """抽出されなかった画像も処理済みとして記録されること。

        保存先に痕跡が残らない画像こそ、記録がなければ毎回再処理される。
        """
        _patch_face_detection(monkeypatch, should_move=False)
        source, dest = _make_source(tmp_path, 3)
        first = _make_state(source, dest, skip_processed=True)
        _run(first)

        second = _make_state(source, dest, skip_processed=True)
        _run(second)

        assert first.skipped == 3
        assert second.already_processed == 3

    def test_failed_files_are_not_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """処理に失敗したファイルは記録されず、次回に再試行されること。"""
        _patch_face_detection(monkeypatch)
        source, dest = _make_source(tmp_path, 2)
        monkeypatch.setattr(
            job_manager_module,
            "detect_faces",
            MagicMock(side_effect=OSError("読み込み失敗")),
        )
        first = _make_state(source, dest, skip_processed=True)
        _run(first)

        _patch_face_detection(monkeypatch)
        second = _make_state(source, dest, skip_processed=True)
        _run(second)

        assert first.errors == 2
        assert second.total == 2
        assert second.already_processed == 0

    def test_records_are_written_under_dest_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """処理済み記録が保存先フォルダ配下に作られること。"""
        _patch_face_detection(monkeypatch)
        source, dest = _make_source(tmp_path, 1)

        _run(_make_state(source, dest, skip_processed=True))

        records = list((dest / PROCESSED_DIR_NAME).glob("*.jsonl"))
        assert len(records) == 1

    def test_records_are_written_even_when_flag_is_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """スキップが無効でも記録は残ること。

        「今回は全部やり直したいが、次回からはスキップしたい」という
        使い方を成立させるため、記録の書き込みはフラグに依存しない。
        """
        _patch_face_detection(monkeypatch)
        source, dest = _make_source(tmp_path, 2)

        _run(_make_state(source, dest, skip_processed=False))
        second = _make_state(source, dest, skip_processed=True)
        _run(second)

        assert second.total == 0
        assert second.already_processed == 2

    def test_complete_message_reports_already_processed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """完了メッセージに already_processed が含まれること。"""
        _patch_face_detection(monkeypatch)
        source, dest = _make_source(tmp_path, 2)
        _run(_make_state(source, dest, skip_processed=True))

        messages = _run(_make_state(source, dest, skip_processed=True))

        payload = json.loads(messages[-1])
        assert payload["type"] == "complete"
        assert payload["already_processed"] == 2
