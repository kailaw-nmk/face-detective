"""job_manager の余白トリミング配線に関するテスト。

顔検出は重い外部依存のためモックし、
「トリミングの有無で保存経路が切り替わるか」だけを検証する。
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw

import job_manager as job_manager_module
from job_manager import JobManager, JobState


def _make_state(
    tmp_path: Path,
    *,
    trim_margins: bool,
) -> tuple[JobState, Path]:
    """テスト用の JobState と入力画像パスを作成する。

    800x600 の白背景の中央に 400x400 のコンテンツを置いた画像を作る。

    Args:
        tmp_path: pytest の一時ディレクトリ。
        trim_margins: 余白トリミングを有効にするかどうか。

    Returns:
        (JobState, 入力画像パス) のタプル。
    """
    source = tmp_path / "src"
    dest = tmp_path / "dest"
    source.mkdir()
    dest.mkdir()

    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    ImageDraw.Draw(img).rectangle((200, 100, 599, 499), fill=(120, 60, 60))
    image_path = source / "page.png"
    img.save(image_path)

    state = JobState(
        job_id="test-job",
        source_folder=source,
        dest_folder=dest,
        threshold=1.0,
        trim_margins=trim_margins,
    )
    return state, image_path


def _patch_face_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """顔検出を「常に抽出対象」を返すモックに差し替える。

    Args:
        monkeypatch: pytest の monkeypatch フィクスチャ。
    """
    result = {
        "should_move": True,
        "max_face_ratio": 10.0,
        "both_eyes_visible": True,
    }
    monkeypatch.setattr(
        job_manager_module, "detect_faces", MagicMock(return_value=result)
    )
    monkeypatch.setattr(
        job_manager_module,
        "detect_faces_from_array",
        MagicMock(return_value=result),
    )


class TestJobStateTrimMargins:
    """JobState の trim_margins 属性のテストクラス。"""

    def test_defaults_to_false(self, tmp_path: Path) -> None:
        """trim_margins を省略すると False になること。"""
        state = JobState(
            job_id="j",
            source_folder=tmp_path,
            dest_folder=tmp_path,
            threshold=5.0,
        )
        assert state.trim_margins is False

    def test_register_job_stores_flag(self, tmp_path: Path) -> None:
        """register_job が trim_margins を pending に保持すること。"""
        manager = JobManager()
        job_id, _dest = manager.register_job(
            source_folder=str(tmp_path), threshold=5.0, trim_margins=True
        )
        assert manager._pending[job_id]["trim_margins"] is True


class TestProcessSingleFile:
    """_process_single_file のテストクラス。"""

    def test_copies_without_trimming_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """トリミング無効時は元画像がそのままのサイズでコピーされること。"""
        _patch_face_detection(monkeypatch)
        state, image_path = _make_state(tmp_path, trim_margins=False)

        JobManager()._process_single_file(state, image_path)

        saved = list(state.dest_folder.rglob("*.png"))
        assert len(saved) == 1
        assert Image.open(saved[0]).size == (800, 600)
        assert state.extracted == 1

    def test_trims_and_reencodes_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """トリミング有効時はコンテンツ矩形だけが保存されること。"""
        _patch_face_detection(monkeypatch)
        state, image_path = _make_state(tmp_path, trim_margins=True)

        JobManager()._process_single_file(state, image_path)

        saved = list(state.dest_folder.rglob("*.png"))
        assert len(saved) == 1
        assert Image.open(saved[0]).size == (400, 400)
        assert state.extracted == 1

    def test_face_ratio_uses_trimmed_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """顔検出にトリミング後のサイズが渡されること。"""
        _patch_face_detection(monkeypatch)
        state, image_path = _make_state(tmp_path, trim_margins=True)

        JobManager()._process_single_file(state, image_path)

        call = job_manager_module.detect_faces_from_array.call_args
        # 位置引数は (image_array, width, height, threshold)
        assert call.args[1] == 400
        assert call.args[2] == 400

    def test_skips_when_face_below_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """閾値未満の画像は保存されず skipped が増えること。"""
        monkeypatch.setattr(
            job_manager_module,
            "detect_faces_from_array",
            MagicMock(
                return_value={
                    "should_move": False,
                    "max_face_ratio": 0.5,
                    "both_eyes_visible": False,
                }
            ),
        )
        state, image_path = _make_state(tmp_path, trim_margins=True)

        JobManager()._process_single_file(state, image_path)

        assert list(state.dest_folder.rglob("*.png")) == []
        assert state.skipped == 1
        assert state.extracted == 0
