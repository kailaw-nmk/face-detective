"""ファイル再帰走査モジュール。

指定フォルダを再帰的にスキャンし、対応する画像ファイルのパスリストを返す。
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tif",
        ".tiff",
        ".webp",
        ".heic",
        ".heif",
    }
)


def scan_folder(folder: Path) -> list[Path]:
    """指定フォルダを再帰的にスキャンして対応画像ファイルのリストを返す。

    大文字・小文字を区別せずに拡張子を判定する。

    Args:
        folder: スキャン対象のフォルダパス。

    Returns:
        対応画像ファイルのパスリスト（ソート済み）。

    Raises:
        ValueError: folder が存在しない、またはディレクトリでない場合。
    """
    if not folder.exists():
        raise ValueError(f"フォルダが存在しません: {folder}")
    if not folder.is_dir():
        raise ValueError(f"指定パスはディレクトリではありません: {folder}")

    image_files: list[Path] = []

    for file_path in folder.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            image_files.append(file_path)
            logger.debug("画像ファイルを検出: %s", file_path)

    image_files.sort()
    logger.info(
        "スキャン完了: %s 件の画像ファイルを検出 (フォルダ: %s)",
        len(image_files),
        folder,
    )
    return image_files
