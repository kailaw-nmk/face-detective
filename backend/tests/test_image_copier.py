"""image_copier モジュールの単体テスト。

copy_image 関数のファイルコピー、フォルダ構成保持、リネームロジック、
および generate_dest_folder 関数の保存先パス生成を検証する。
"""

from pathlib import Path

import pytest
from PIL import Image

from image_copier import copy_image, generate_dest_folder


def _create_image_file(path: Path, size: tuple[int, int] = (10, 10)) -> Path:
    """指定パスに小さな PNG 画像を作成するヘルパー関数。

    Args:
        path: 作成するファイルのパス。
        size: 画像サイズ（幅, 高さ）。

    Returns:
        作成したファイルのパス。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color=(100, 100, 100))
    img.save(path)
    return path


class TestGenerateDestFolder:
    """generate_dest_folder 関数のテスト群。"""

    def test_appends_face_suffix(self) -> None:
        """フォルダ名の末尾に _face が付与されることを確認する。"""
        result = generate_dest_folder(Path("C:/Photos/Family"))
        assert result == Path("C:/Photos/Family_face")

    def test_unix_style_path(self) -> None:
        """Unix スタイルのパスでも正しく動作することを確認する。"""
        result = generate_dest_folder(Path("/data/pics"))
        assert result == Path("/data/pics_face")

    def test_same_parent_directory(self) -> None:
        """生成されたパスが入力と同じ親ディレクトリにあることを確認する。"""
        source = Path("D:/Users/Photos/vacation")
        result = generate_dest_folder(source)
        assert result.parent == source.parent


class TestCopyImageBasic:
    """基本的なファイルコピー動作を検証するテスト群。"""

    def test_copy_image_basic(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """ファイルがコピー先に存在し、コピー元も残ることを確認する。"""
        src = _create_image_file(tmp_source_dir / "photo.jpg")

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir)

        assert result_path.exists()
        assert src.exists()  # コピーなので元ファイルは残る

    def test_copy_image_returns_dest_path(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """copy_image が実際のコピー先パスを返すことを確認する。"""
        src = _create_image_file(tmp_source_dir / "image.png")

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir, face_ratio=12.5)

        assert result_path == tmp_dest_dir / "image_12.5pct.png"

    def test_copy_image_preserves_filename(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """ファイル名に顔面積比が付与されることを確認する。"""
        src = _create_image_file(tmp_source_dir / "myphoto.jpeg")

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir, face_ratio=5.3)

        assert result_path.name == "myphoto_5.3pct.jpeg"

    def test_copy_image_preserves_content(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """コピー後にファイルの内容が変わらないことを確認する。"""
        src = tmp_source_dir / "data.png"
        original_bytes = b"PNG_FAKE_CONTENT_12345"
        src.write_bytes(original_bytes)

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir)

        assert result_path.read_bytes() == original_bytes


class TestCopyImagePreservesStructure:
    """サブフォルダ構成の保持を検証するテスト群。"""

    def test_preserves_single_subfolder(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """1階層のサブフォルダ構成が保持されることを確認する。"""
        src = _create_image_file(tmp_source_dir / "2024" / "photo.jpg")

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir)

        assert result_path == tmp_dest_dir / "2024" / "photo_0.0pct.jpg"
        assert result_path.exists()

    def test_preserves_nested_subfolders(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """複数階層のサブフォルダ構成が保持されることを確認する。"""
        src = _create_image_file(
            tmp_source_dir / "2024" / "vacation" / "beach" / "img.jpg"
        )

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir)

        assert result_path == tmp_dest_dir / "2024" / "vacation" / "beach" / "img_0.0pct.jpg"
        assert result_path.exists()

    def test_creates_intermediate_directories(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """コピー先の中間ディレクトリが自動作成されることを確認する。"""
        src = _create_image_file(tmp_source_dir / "a" / "b" / "c" / "photo.jpg")

        copy_image(src, tmp_source_dir, tmp_dest_dir)

        assert (tmp_dest_dir / "a" / "b" / "c").is_dir()

    def test_multiple_files_different_subfolders(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """異なるサブフォルダの複数ファイルがそれぞれ正しい場所にコピーされることを確認する。"""
        src1 = _create_image_file(tmp_source_dir / "2024" / "a.jpg")
        src2 = _create_image_file(tmp_source_dir / "2025" / "b.jpg")

        result1 = copy_image(src1, tmp_source_dir, tmp_dest_dir)
        result2 = copy_image(src2, tmp_source_dir, tmp_dest_dir)

        assert result1 == tmp_dest_dir / "2024" / "a_0.0pct.jpg"
        assert result2 == tmp_dest_dir / "2025" / "b_0.0pct.jpg"
        assert result1.exists()
        assert result2.exists()


class TestCopyImageRenameOnConflict:
    """ファイル名重複時のリネーム動作を検証するテスト群。"""

    def test_rename_on_conflict(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """コピー先に同名ファイルが存在する場合にリネームされることを確認する。"""
        _create_image_file(tmp_dest_dir / "photo_0.0pct.jpg")
        src = _create_image_file(tmp_source_dir / "photo.jpg")

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir)

        assert result_path.name == "photo_0.0pct_001.jpg"
        assert result_path.exists()
        assert src.exists()  # コピーなので元ファイルは残る

    def test_multiple_conflicts(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """複数の重複がある場合に連番が正しくインクリメントされることを確認する。"""
        _create_image_file(tmp_dest_dir / "photo_0.0pct.jpg")
        _create_image_file(tmp_dest_dir / "photo_0.0pct_001.jpg")
        _create_image_file(tmp_dest_dir / "photo_0.0pct_002.jpg")

        src = _create_image_file(tmp_source_dir / "photo.jpg")

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir)

        assert result_path.name == "photo_0.0pct_003.jpg"
        assert result_path.exists()

    def test_conflict_preserves_extension(
        self, tmp_source_dir: Path, tmp_dest_dir: Path
    ) -> None:
        """リネーム後も元の拡張子が保持されることを確認する。"""
        _create_image_file(tmp_dest_dir / "image.PNG")
        src = tmp_source_dir / "image.PNG"
        src.write_bytes(b"\x00")

        result_path = copy_image(src, tmp_source_dir, tmp_dest_dir)

        assert result_path.suffix == ".PNG"


class TestCopyImageErrorHandling:
    """エラーハンドリングを検証するテスト群。"""

    def test_source_not_found(self, tmp_dest_dir: Path, tmp_path: Path) -> None:
        """存在しないコピー元ファイルを指定した場合に FileNotFoundError が送出されることを確認する。"""
        missing_src = tmp_path / "source" / "nonexistent.jpg"
        source_root = tmp_path / "source"
        source_root.mkdir(exist_ok=True)

        with pytest.raises(FileNotFoundError, match="コピー元ファイルが存在しません"):
            copy_image(missing_src, source_root, tmp_dest_dir)

    def test_source_not_found_message(
        self, tmp_dest_dir: Path, tmp_path: Path
    ) -> None:
        """FileNotFoundError のメッセージにコピー元パスが含まれることを確認する。"""
        missing_src = tmp_path / "source" / "missing_file.jpg"
        source_root = tmp_path / "source"
        source_root.mkdir(exist_ok=True)

        with pytest.raises(FileNotFoundError) as exc_info:
            copy_image(missing_src, source_root, tmp_dest_dir)

        assert str(missing_src) in str(exc_info.value)
