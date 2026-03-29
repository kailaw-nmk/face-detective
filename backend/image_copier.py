"""画像ファイルコピーモジュール。

画像ファイルをサブフォルダ構成を保持したまま保存先フォルダへコピーする。
ファイル名が重複する場合は連番サフィックスを付与してリネームする。
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_dest_folder(source_folder: Path) -> Path:
    """入力フォルダパスから保存先フォルダパスを自動生成する。

    入力フォルダ名の末尾に ``_face`` を付与した同階層のフォルダパスを返す。

    Args:
        source_folder: 走査対象フォルダのパス。

    Returns:
        保存先フォルダのパス（例: ``C:/Photos/Family`` → ``C:/Photos/Family_face``）。
    """
    return source_folder.parent / (source_folder.name + "_face")


def copy_image(src: Path, source_root: Path, dest_root: Path) -> Path:
    """画像ファイルをサブフォルダ構成を保持したまま保存先へコピーする。

    入力フォルダからの相対パスを計算し、保存先フォルダ内に同じディレクトリ
    構造を再現してコピーする。中間ディレクトリは自動的に作成する。
    ファイル名が重複する場合は ``{stem}_{number:03d}.{ext}`` 形式で
    リネームし、一意になるまで連番をインクリメントする。

    Args:
        src: コピー元の画像ファイルパス。
        source_root: 走査対象のルートフォルダパス。
        dest_root: 保存先ルートフォルダのパス。

    Returns:
        実際に保存されたファイルの完全パス。

    Raises:
        FileNotFoundError: src が存在しない場合。
        OSError: ファイルコピーに失敗した場合。
    """
    if not src.exists():
        raise FileNotFoundError(f"コピー元ファイルが存在しません: {src}")

    rel = src.relative_to(source_root)
    dest_path = dest_root / rel

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        dest_dir = dest_path.parent
        counter = 1
        while True:
            new_name = f"{stem}_{counter:03d}{suffix}"
            dest_path = dest_dir / new_name
            if not dest_path.exists():
                break
            counter += 1
        logger.debug(
            "ファイル名重複のためリネーム: %s → %s", src.name, dest_path.name
        )

    shutil.copy2(str(src), str(dest_path))
    logger.info("ファイルをコピーしました: %s → %s", src, dest_path)
    return dest_path
