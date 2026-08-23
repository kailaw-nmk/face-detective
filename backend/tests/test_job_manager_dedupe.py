"""job_manager の重複判定に関するテスト。

顔検出は重い外部依存のためモックし、重複判定の分岐と退避のみを検証する。
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

import job_manager as job_manager_module
from image_copier import DUPLICATES_DIR_NAME
from job_manager import JobManager, JobState


def _patterned_image(seed: int, size: tuple[int, int] = (240, 320)) -> Image.Image:
    """seed ごとに明確に異なる模様の RGB 画像を作る。

    Args:
        seed: 模様を決める整数。
        size: (width, height)。

    Returns:
        生成した RGB 画像。
    """
    width, height = size
    ys, xs = np.mgrid[0:height, 0:width]
    base = (xs * (seed + 1) // 7 + ys * (seed + 3) // 5) % 256
    block = ((xs // (8 + seed)) + (ys // (6 + seed))) % 2 * 60
    arr = np.clip(base + block, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([arr, arr, arr]), mode="RGB")


def _margined_image(
    size: tuple[int, int] = (800, 600),
    inner_size: tuple[int, int] = (400, 400),
) -> Image.Image:
    """白背景の中央にカラー矩形を置いた、余白のある RGB 画像を作る。

    Args:
        size: (width, height)。全体サイズ。
        inner_size: (width, height)。中央に置くカラー矩形のサイズ。

    Returns:
        生成した RGB 画像。トリミングすると inner_size に収束するはず。
    """
    width, height = size
    inner_w, inner_h = inner_size
    arr = np.full((height, width, 3), 255, dtype=np.uint8)
    top = (height - inner_h) // 2
    left = (width - inner_w) // 2
    arr[top : top + inner_h, left : left + inner_w] = (30, 60, 200)
    return Image.fromarray(arr, mode="RGB")


def _make_state(tmp_path: Path, *, dedupe: bool, seeds: list[int]) -> JobState:
    """入力画像を作り、対応する JobState を返す。

    Args:
        tmp_path: pytest の一時ディレクトリ。
        dedupe: 重複判定を有効にするかどうか。
        seeds: 生成する画像の seed 列。同じ値を並べれば重複になる。

    Returns:
        構築した JobState。
    """
    source = tmp_path / "src"
    dest = tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    for i, seed in enumerate(seeds):
        _patterned_image(seed).save(source / f"page_{i:03d}.png")

    return JobState(
        job_id="test-job",
        source_folder=source,
        dest_folder=dest,
        threshold=1.0,
        dedupe=dedupe,
    )


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
        job_manager_module, "detect_faces_from_array", MagicMock(return_value=result)
    )


class TestJobStateDedupe:
    """JobState の重複判定用フィールドのテストクラス。"""

    def test_defaults_to_disabled(self, tmp_path: Path) -> None:
        """dedupe を省略すると False で、カウンタが 0 であること。"""
        state = JobState(
            job_id="j",
            source_folder=tmp_path,
            dest_folder=tmp_path,
            threshold=5.0,
        )

        assert state.dedupe is False
        assert state.duplicates == 0

    def test_register_job_stores_flags(self, tmp_path: Path) -> None:
        """register_job が dedupe 設定を pending に保持すること。"""
        manager = JobManager()

        job_id, _dest = manager.register_job(
            source_folder=str(tmp_path),
            threshold=5.0,
            dedupe=True,
            dedupe_max_distance=4,
        )

        assert manager._pending[job_id]["dedupe"] is True
        assert manager._pending[job_id]["dedupe_max_distance"] == 4


class TestCheckDuplicate:
    """_check_duplicate のテストクラス。"""

    def test_first_image_is_not_duplicate(self, tmp_path: Path) -> None:
        """最初の画像は重複ではなく、下流へ渡す画像が返ること。"""
        state = _make_state(tmp_path, dedupe=True, seeds=[1])
        target = state.source_folder / "page_000.png"

        outcome = JobManager()._check_duplicate(state, target)

        assert outcome.is_duplicate is False
        assert outcome.image is not None
        assert len(state.duplicate_index) == 1

    def test_second_identical_image_is_duplicate(self, tmp_path: Path) -> None:
        """同一画像の 2 枚目が重複と判定され、_duplicates に退避されること。"""
        state = _make_state(tmp_path, dedupe=True, seeds=[1, 1])
        manager = JobManager()
        first = state.source_folder / "page_000.png"
        second = state.source_folder / "page_001.png"

        manager._check_duplicate(state, first)
        outcome = manager._check_duplicate(state, second)

        assert outcome.is_duplicate is True
        assert outcome.image is None
        assert state.duplicates == 1
        assert (state.dest_folder / DUPLICATES_DIR_NAME / "page_001.png").exists()

    def test_different_image_is_not_duplicate(self, tmp_path: Path) -> None:
        """別の画像は重複と判定されないこと。"""
        state = _make_state(tmp_path, dedupe=True, seeds=[1, 9])
        manager = JobManager()

        manager._check_duplicate(state, state.source_folder / "page_000.png")
        outcome = manager._check_duplicate(
            state, state.source_folder / "page_001.png"
        )

        assert outcome.is_duplicate is False
        assert state.duplicates == 0

    def test_reports_whether_image_was_trimmed(self, tmp_path: Path) -> None:
        """トリミングが無効なら trimmed が False で返ること。

        呼び出し側はこの値で「再エンコードして保存するか、バイトコピーで無劣化のまま保存するか」を決めるため、
        画像そのものと同じくらい重要な戻り値である。
        """
        state = _make_state(tmp_path, dedupe=True, seeds=[1])
        state.trim_margins = False

        outcome = JobManager()._check_duplicate(
            state, state.source_folder / "page_000.png"
        )

        assert outcome.trimmed is False

    def test_reports_trimmed_true_when_margins_are_actually_trimmed(
        self, tmp_path: Path
    ) -> None:
        """余白のある画像を trim_margins=True で判定すると trimmed が True になること。

        誤って False が返ると _process_single_file が save_spread_image ではなく
        copy_image を選び、トリミングされていない元ファイルをそのままコピーして
        しまう（顔面積比のタグだけがトリミング後の値という不整合を生む）。
        """
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        original = _margined_image(size=(800, 600), inner_size=(400, 400))
        original.save(source / "page_000.png")

        state = JobState(
            job_id="test-job",
            source_folder=source,
            dest_folder=dest,
            threshold=1.0,
            dedupe=True,
            trim_margins=True,
        )

        outcome = JobManager()._check_duplicate(state, source / "page_000.png")

        assert outcome.trimmed is True
        assert outcome.image is not None
        assert outcome.image.size[0] < original.size[0]
        assert outcome.image.size[1] < original.size[1]

    def test_hash_failure_falls_through_to_normal_processing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ハッシュ計算が失敗しても例外を投げず、通常処理に進ませること。"""
        state = _make_state(tmp_path, dedupe=True, seeds=[1])

        def _raise(_image: Image.Image) -> None:
            raise ValueError("ハッシュ失敗をシミュレート")

        monkeypatch.setattr(job_manager_module, "compute_dhash", _raise)

        outcome = JobManager()._check_duplicate(
            state, state.source_folder / "page_000.png"
        )

        assert outcome.is_duplicate is False
        assert outcome.image is None
        assert state.duplicates == 0


class TestRunJobDedupe:
    """ジョブ全体での重複除外のテストクラス。"""

    def test_duplicates_are_excluded_from_extraction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """重複画像が抽出されず duplicates に計上されること。"""
        _patch_face_detection(monkeypatch)
        state = _make_state(tmp_path, dedupe=True, seeds=[1, 1, 9])
        messages: list[str] = []

        async def _send(message: str) -> None:
            messages.append(message)

        asyncio.run(JobManager()._run_job(state, _send))

        assert state.duplicates == 1
        assert state.extracted == 2
        assert '"duplicates": 1' in messages[-1]

    def test_disabled_dedupe_extracts_everything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dedupe が無効なら重複も従来どおり抽出されること。"""
        _patch_face_detection(monkeypatch)
        state = _make_state(tmp_path, dedupe=False, seeds=[1, 1, 9])

        async def _send(_message: str) -> None:
            return None

        asyncio.run(JobManager()._run_job(state, _send))

        assert state.duplicates == 0
        assert state.extracted == 3
