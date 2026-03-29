"""file_scanner モジュールの単体テスト。

scan_folder 関数と SUPPORTED_EXTENSIONS の動作を検証する。
"""

from pathlib import Path

import pytest

from file_scanner import SUPPORTED_EXTENSIONS, scan_folder


class TestScanFolderFindsImages:
    """対応拡張子の画像ファイルを正しく検出できることを確認するテスト群。"""

    def test_scan_folder_finds_images(self, tmp_source_dir: Path) -> None:
        """各対応拡張子のファイルを配置し、すべて検出されることを確認する。"""
        extensions = [".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"]
        created: list[Path] = []
        for ext in extensions:
            f = tmp_source_dir / f"image{ext}"
            f.write_bytes(b"\x00")
            created.append(f)

        result = scan_folder(tmp_source_dir)

        assert sorted(result) == sorted(created)

    def test_scan_folder_ignores_non_images(self, tmp_source_dir: Path) -> None:
        """.txt や .pdf などの非画像ファイルが結果に含まれないことを確認する。"""
        (tmp_source_dir / "document.txt").write_text("hello")
        (tmp_source_dir / "report.pdf").write_bytes(b"%PDF")
        (tmp_source_dir / "data.csv").write_text("a,b,c")
        (tmp_source_dir / "archive.zip").write_bytes(b"PK")

        result = scan_folder(tmp_source_dir)

        assert result == []

    def test_scan_folder_case_insensitive(self, tmp_source_dir: Path) -> None:
        """大文字拡張子（.JPG, .Png など）のファイルも検出されることを確認する。"""
        upper_jpg = tmp_source_dir / "photo.JPG"
        mixed_png = tmp_source_dir / "image.Png"
        upper_jpeg = tmp_source_dir / "pic.JPEG"
        upper_jpg.write_bytes(b"\x00")
        mixed_png.write_bytes(b"\x00")
        upper_jpeg.write_bytes(b"\x00")

        result = scan_folder(tmp_source_dir)

        assert sorted(result) == sorted([upper_jpg, mixed_png, upper_jpeg])

    def test_scan_folder_recursive(self, tmp_source_dir: Path) -> None:
        """ネストされたサブディレクトリ内の画像ファイルも再帰的に検出されることを確認する。"""
        sub1 = tmp_source_dir / "sub1"
        sub2 = tmp_source_dir / "sub1" / "sub2"
        sub1.mkdir()
        sub2.mkdir()

        root_img = tmp_source_dir / "root.jpg"
        sub1_img = sub1 / "sub1.png"
        sub2_img = sub2 / "sub2.jpeg"
        root_img.write_bytes(b"\x00")
        sub1_img.write_bytes(b"\x00")
        sub2_img.write_bytes(b"\x00")

        result = scan_folder(tmp_source_dir)

        assert sorted(result) == sorted([root_img, sub1_img, sub2_img])

    def test_scan_folder_nonexistent_raises(self, tmp_path: Path) -> None:
        """存在しないフォルダを指定した場合に ValueError が送出されることを確認する。"""
        nonexistent = tmp_path / "does_not_exist"

        with pytest.raises(ValueError, match="フォルダが存在しません"):
            scan_folder(nonexistent)

    def test_scan_folder_not_directory_raises(self, tmp_path: Path) -> None:
        """ファイルパスをフォルダとして渡した場合に ValueError が送出されることを確認する。"""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")

        with pytest.raises(ValueError, match="ディレクトリではありません"):
            scan_folder(file_path)

    def test_scan_folder_returns_sorted_list(self, tmp_source_dir: Path) -> None:
        """返却されるリストがソート済みであることを確認する。"""
        for name in ["c.jpg", "a.png", "b.jpeg"]:
            (tmp_source_dir / name).write_bytes(b"\x00")

        result = scan_folder(tmp_source_dir)

        assert result == sorted(result)

    def test_scan_folder_empty_directory(self, tmp_source_dir: Path) -> None:
        """空のディレクトリをスキャンした場合に空リストが返ることを確認する。"""
        result = scan_folder(tmp_source_dir)

        assert result == []

    def test_scan_folder_mixed_files(self, tmp_source_dir: Path) -> None:
        """画像ファイルと非画像ファイルが混在する場合、画像のみが返ることを確認する。"""
        img = tmp_source_dir / "photo.jpg"
        txt = tmp_source_dir / "notes.txt"
        img.write_bytes(b"\x00")
        txt.write_text("notes")

        result = scan_folder(tmp_source_dir)

        assert result == [img]


class TestSupportedExtensions:
    """SUPPORTED_EXTENSIONS の内容を検証するテスト群。"""

    def test_supported_extensions_is_frozenset(self) -> None:
        """SUPPORTED_EXTENSIONS が frozenset であることを確認する。"""
        assert isinstance(SUPPORTED_EXTENSIONS, frozenset)

    def test_supported_extensions_contains_expected(self) -> None:
        """必須の拡張子がすべて含まれていることを確認する。"""
        expected = {
            ".jpg", ".jpeg", ".png", ".bmp",
            ".tif", ".tiff", ".webp", ".heic", ".heif",
        }
        assert expected.issubset(SUPPORTED_EXTENSIONS)

    def test_supported_extensions_are_lowercase(self) -> None:
        """すべての拡張子が小文字で定義されていることを確認する。"""
        for ext in SUPPORTED_EXTENSIONS:
            assert ext == ext.lower(), f"拡張子が小文字でない: {ext}"
