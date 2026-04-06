"""画像ファイルコピーモジュール。

画像ファイルをサブフォルダ構成を保持したまま保存先フォルダへコピーする。
ファイル名が重複する場合は連番サフィックスを付与してリネームする。
"""

import logging
import shutil
from pathlib import Path

from PIL import Image

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


def copy_image(
    src: Path,
    source_root: Path,
    dest_root: Path,
    face_ratio: float = 0.0,
) -> Path:
    """画像ファイルをサブフォルダ構成を保持したまま保存先へコピーする。

    入力フォルダからの相対パスを計算し、保存先フォルダ内に同じディレクトリ
    構造を再現してコピーする。中間ディレクトリは自動的に作成する。
    ファイル名が重複する場合は ``{stem}_{number:03d}.{ext}`` 形式で
    リネームし、一意になるまで連番をインクリメントする。

    Args:
        src: コピー元の画像ファイルパス。
        source_root: 走査対象のルートフォルダパス。
        dest_root: 保存先ルートフォルダのパス。
        face_ratio: 顔面積比 (%)。ファイル名末尾に付与する。

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

    # ファイル名に顔面積比を付与する
    stem = dest_path.stem
    ext = dest_path.suffix
    ratio_tag = f"_{face_ratio:.1f}pct"
    dest_dir = dest_path.parent
    dest_path = dest_dir / f"{stem}{ratio_tag}{ext}"

    if dest_path.exists():
        counter = 1
        while True:
            new_name = f"{stem}{ratio_tag}_{counter:03d}{ext}"
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


def save_spread_image(
    image: Image.Image,
    original_path: Path,
    suffix: str,
    source_root: Path,
    dest_root: Path,
    face_ratio: float = 0.0,
) -> Path:
    """Pillow Image を保存先フォルダに直接書き出す。

    見開き分割処理で生成された画像を、元ファイルのパス構造を保持しつつ
    suffix 付きのファイル名で保存先に書き出す。

    Args:
        image: 保存する PIL 画像。
        original_path: 元画像のファイルパス。
        suffix: ファイル名に付与するサフィックス（例: "_L", "_R", ""）。
        source_root: 走査対象の基底フォルダ。
        dest_root: 保存先の基底フォルダ。
        face_ratio: 顔面積比 (%)。ファイル名末尾に付与する。

    Returns:
        実際に保存されたファイルパス。
    """
    relative = original_path.relative_to(source_root)
    dest_dir = dest_root / relative.parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    stem = original_path.stem
    ext = original_path.suffix
    ratio_tag = f"_{face_ratio:.1f}pct"
    dest_path = dest_dir / f"{stem}{suffix}{ratio_tag}{ext}"

    if dest_path.exists():
        counter = 1
        while True:
            new_name = f"{stem}{suffix}{ratio_tag}_{counter:03d}{ext}"
            dest_path = dest_dir / new_name
            if not dest_path.exists():
                break
            counter += 1
        logger.debug(
            "ファイル名重複のためリネーム: %s → %s",
            f"{stem}{suffix}{ratio_tag}{ext}",
            dest_path.name,
        )

    ext_lower = ext.lower()
    if ext_lower in (".jpg", ".jpeg"):
        image.save(dest_path, "JPEG", quality=95)
    elif ext_lower == ".png":
        image.save(dest_path, "PNG")
    else:
        image.save(dest_path)

    logger.info("分割画像を保存しました: %s", dest_path)
    return dest_path
