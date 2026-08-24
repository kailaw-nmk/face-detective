"""processed_index モジュールの単体テスト。

テスト対象:
    - compute_settings_hash: 安定性 / 設定差での分岐 / キー順序の非依存
    - ProcessedIndex: 記録と再読込 / サイズ・更新日時の変化による再処理 /
      設定ハッシュごとの分離 / 途中終了時の耐性
"""

import json
from pathlib import Path

import pytest

from processed_index import (
    PROCESSED_DIR_NAME,
    ProcessedIndex,
    compute_settings_hash,
)


def _write_file(path: Path, content: bytes = b"hello") -> Path:
    """指定パスにファイルを作成するヘルパー。

    Args:
        path: 作成するファイルのパス。
        content: 書き込む内容。

    Returns:
        作成したファイルのパス。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture()
def roots(tmp_path: Path) -> tuple[Path, Path]:
    """入力ルートと保存先ルートのペアを返す。

    Returns:
        (source_root, dest_root) のタプル。
    """
    source = tmp_path / "src"
    dest = tmp_path / "src_face"
    source.mkdir()
    dest.mkdir()
    return source, dest


class TestComputeSettingsHash:
    """compute_settings_hash 関数のテスト群。"""

    def test_same_settings_produce_same_hash(self) -> None:
        """同じ設定なら同じハッシュになること。"""
        settings = {"threshold": 5.0, "dedupe": True}

        assert compute_settings_hash(settings) == compute_settings_hash(settings)

    def test_key_order_does_not_matter(self) -> None:
        """辞書のキー順序が違ってもハッシュが一致すること。

        呼び出し側が引数を並べ替えただけで記録が分断されると、
        利用者から見れば「同じ設定なのに再処理された」という不具合になる。
        """
        first = compute_settings_hash({"threshold": 5.0, "dedupe": True})
        second = compute_settings_hash({"dedupe": True, "threshold": 5.0})

        assert first == second

    def test_different_settings_produce_different_hash(self) -> None:
        """設定値が違えば別のハッシュになること。"""
        first = compute_settings_hash({"threshold": 5.0})
        second = compute_settings_hash({"threshold": 6.0})

        assert first != second

    def test_hash_is_filename_safe(self) -> None:
        """ハッシュがファイル名に使える短い十六進文字列であること。"""
        value = compute_settings_hash({"threshold": 5.0})

        assert len(value) == 12
        assert all(char in "0123456789abcdef" for char in value)


class TestProcessedIndexRoundTrip:
    """記録と再読込に関するテスト群。"""

    def test_unmarked_file_is_not_processed(self, roots: tuple[Path, Path]) -> None:
        """記録していないファイルは未処理と判定されること。"""
        source, dest = roots
        target = _write_file(source / "a.jpg")

        index = ProcessedIndex(source, dest, "abc123456789")

        assert index.is_processed(target) is False

    def test_marked_file_is_processed_within_same_instance(
        self, roots: tuple[Path, Path]
    ) -> None:
        """mark 直後に同じインスタンスで処理済みと判定されること。"""
        source, dest = roots
        target = _write_file(source / "a.jpg")
        index = ProcessedIndex(source, dest, "abc123456789")

        index.mark(target)

        assert index.is_processed(target) is True

    def test_marked_file_is_processed_after_reload(
        self, roots: tuple[Path, Path]
    ) -> None:
        """close 後に読み直したインスタンスでも処理済みと判定されること。"""
        source, dest = roots
        target = _write_file(source / "sub" / "a.jpg")
        first = ProcessedIndex(source, dest, "abc123456789")
        first.mark(target)
        first.close()

        second = ProcessedIndex(source, dest, "abc123456789")

        assert second.is_processed(target) is True

    def test_record_file_is_written_under_dest_root(
        self, roots: tuple[Path, Path]
    ) -> None:
        """記録ファイルが保存先ルート配下の所定の場所に作られること。

        保存先フォルダごと削除すれば記録も消える、という対応関係を保証する。
        """
        source, dest = roots
        target = _write_file(source / "a.jpg")
        index = ProcessedIndex(source, dest, "abc123456789")

        index.mark(target)
        index.close()

        record = dest / PROCESSED_DIR_NAME / "abc123456789.jsonl"
        assert record.exists()

    def test_creates_dest_root_when_missing(self, tmp_path: Path) -> None:
        """保存先ルートが未作成でも記録できること。

        抽出が 1 件も発生しないジョブでは保存先が作られないため、
        記録側で作成できないと最初の 1 件で失敗する。
        """
        source = tmp_path / "src"
        source.mkdir()
        dest = tmp_path / "src_face"
        target = _write_file(source / "a.jpg")
        index = ProcessedIndex(source, dest, "abc123456789")

        index.mark(target)
        index.close()

        assert (dest / PROCESSED_DIR_NAME / "abc123456789.jsonl").exists()


class TestProcessedIndexInvalidation:
    """ファイル内容が変わった場合の再処理に関するテスト群。"""

    def test_size_change_makes_file_unprocessed(
        self, roots: tuple[Path, Path]
    ) -> None:
        """サイズが変わったファイルは再び未処理と判定されること。"""
        source, dest = roots
        target = _write_file(source / "a.jpg", b"hello")
        index = ProcessedIndex(source, dest, "abc123456789")
        index.mark(target)

        target.write_bytes(b"hello world")

        assert index.is_processed(target) is False

    def test_mtime_change_makes_file_unprocessed(
        self, roots: tuple[Path, Path]
    ) -> None:
        """更新日時が変わったファイルは再び未処理と判定されること。

        サイズが同じままの差し替えを拾うための判定なので、
        サイズ変化のテストとは別に必要。
        """
        source, dest = roots
        target = _write_file(source / "a.jpg", b"hello")
        index = ProcessedIndex(source, dest, "abc123456789")
        index.mark(target)
        stat = target.stat()

        import os

        os.utime(target, (stat.st_atime, stat.st_mtime + 120))

        assert index.is_processed(target) is False

    def test_same_name_in_different_subfolder_is_unprocessed(
        self, roots: tuple[Path, Path]
    ) -> None:
        """別サブフォルダの同名・同サイズ・同日時ファイルは未処理であること。

        記録キーが相対パスを含まないと、階層違いの同名ファイルが
        まとめてスキップされてしまう。
        """
        source, dest = roots
        first = _write_file(source / "a" / "photo.jpg", b"hello")
        second = _write_file(source / "b" / "photo.jpg", b"hello")
        stat = first.stat()

        import os

        os.utime(second, (stat.st_atime, stat.st_mtime))

        index = ProcessedIndex(source, dest, "abc123456789")
        index.mark(first)

        assert index.is_processed(second) is False


class TestProcessedIndexSettingsSeparation:
    """設定ハッシュごとの記録分離に関するテスト群。"""

    def test_other_settings_hash_does_not_see_records(
        self, roots: tuple[Path, Path]
    ) -> None:
        """別の設定ハッシュのインデックスからは処理済みに見えないこと。"""
        source, dest = roots
        target = _write_file(source / "a.jpg")
        first = ProcessedIndex(source, dest, "aaaaaaaaaaaa")
        first.mark(target)
        first.close()

        second = ProcessedIndex(source, dest, "bbbbbbbbbbbb")

        assert second.is_processed(target) is False


class TestProcessedIndexResilience:
    """記録ファイルが壊れている場合の耐性に関するテスト群。"""

    def test_partial_last_line_is_ignored(self, roots: tuple[Path, Path]) -> None:
        """途中で切れた最終行を無視し、それ以前の行は読めること。

        ジョブを強制終了した直後の記録ファイルを想定する。
        """
        source, dest = roots
        first = _write_file(source / "a.jpg")
        second = _write_file(source / "b.jpg")
        index = ProcessedIndex(source, dest, "abc123456789")
        index.mark(first)
        index.close()

        record = dest / PROCESSED_DIR_NAME / "abc123456789.jsonl"
        with record.open("a", encoding="utf-8") as handle:
            handle.write('{"p": "b.jpg", "s": 5')

        reloaded = ProcessedIndex(source, dest, "abc123456789")

        assert reloaded.is_processed(first) is True
        assert reloaded.is_processed(second) is False

    def test_file_outside_source_root_is_not_processed(
        self, roots: tuple[Path, Path]
    ) -> None:
        """入力ルート外のパスを渡しても例外を投げず未処理を返すこと。"""
        source, dest = roots
        outside = _write_file(dest.parent / "outside.jpg")
        index = ProcessedIndex(source, dest, "abc123456789")

        assert index.is_processed(outside) is False

    def test_flushes_records_periodically(self, roots: tuple[Path, Path]) -> None:
        """close 前でも一定件数ごとに記録がディスクへ書き出されること。

        長時間ジョブが中断されたときに進捗を失わないための保証。
        """
        source, dest = roots
        index = ProcessedIndex(source, dest, "abc123456789")

        for i in range(150):
            index.mark(_write_file(source / f"f{i:03d}.jpg"))

        record = dest / PROCESSED_DIR_NAME / "abc123456789.jsonl"
        lines = [
            line
            for line in record.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) >= 100
        assert json.loads(lines[0])["p"] == "f000.jpg"

    def test_close_is_idempotent(self, roots: tuple[Path, Path]) -> None:
        """close を二度呼んでも例外にならないこと。"""
        source, dest = roots
        index = ProcessedIndex(source, dest, "abc123456789")
        index.mark(_write_file(source / "a.jpg"))

        index.close()
        index.close()
