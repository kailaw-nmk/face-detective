"""処理済み画像の記録モジュール。

ジョブをまたいで「どのファイルを処理したか」を保存先フォルダ配下に永続化し、
次回以降のスキャンで同じ画像を再処理しないようにする。

記録は保存先ルートの ``.processed/<設定ハッシュ>.jsonl`` に置く。保存先フォルダを
削除すれば記録も一緒に消えるため、「全部やり直したい」ときの操作が
「保存先フォルダを消す」の一手で済む。

設定ごとにファイルを分けるのは、顔サイズ閾値などを変えたときに
「前回スキップされた画像」を拾い直せるようにするため。同じ設定で再実行した
場合だけスキップが効く。
"""

import hashlib
import json
import logging
from pathlib import Path
from types import TracebackType
from typing import Any

logger = logging.getLogger(__name__)

# 記録ファイルを置く保存先ルート直下のフォルダ名
PROCESSED_DIR_NAME = ".processed"

# 設定ハッシュの文字数（ファイル名に使うため短く切り詰める）
SETTINGS_HASH_LENGTH = 12

# この件数ごとに追記バッファをディスクへ書き出す。
# NAS 越しでは 1 件ごとの flush が往復コストになるため間引くが、
# ジョブが中断されたときの取りこぼしを小さく保つ程度には頻繁に行う。
_FLUSH_INTERVAL = 100


def compute_settings_hash(settings: dict[str, Any]) -> str:
    """設定辞書から記録ファイル名に使うハッシュを求める。

    キーの並び順に依存しないよう、JSON 化の際にキーをソートする。
    呼び出し側が引数の順序を変えただけで記録が分断されると、
    利用者から見れば「同じ設定なのに再処理された」という不具合になる。

    Args:
        settings: 記録を分ける対象となる設定値の辞書。

    Returns:
        十六進小文字の短いハッシュ文字列。
    """
    payload = json.dumps(settings, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest[:SETTINGS_HASH_LENGTH]


class ProcessedIndex:
    """処理済みファイルの記録を読み書きするクラス。

    判定キーは「入力ルートからの相対パス・ファイルサイズ・更新日時（秒）」の
    3 つ組。画像を開かずに済むため NAS 越しでも高速で、かつ差し替えられた
    画像は自動的に再処理される。
    """

    def __init__(
        self, source_root: Path, dest_root: Path, settings_hash: str
    ) -> None:
        """記録を読み込んでインデックスを初期化する。

        Args:
            source_root: 走査対象のルートフォルダ。相対パスの基準になる。
            dest_root: 保存先ルートフォルダ。この直下に記録を置く。
            settings_hash: :func:`compute_settings_hash` が返した設定ハッシュ。
        """
        self._source_root = source_root
        self._record_path = dest_root / PROCESSED_DIR_NAME / f"{settings_hash}.jsonl"
        self._keys: set[tuple[str, int, int]] = set()
        self._handle: Any = None
        self._unflushed = 0
        self._load()

    def __len__(self) -> int:
        """記録済みキーの件数を返す。

        Returns:
            読み込み済み・追加済みを合わせたキーの総数。
        """
        return len(self._keys)

    def __enter__(self) -> "ProcessedIndex":
        """with 文の開始時に自身を返す。

        Returns:
            このインデックス。
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """with 文の終了時に記録を閉じる。

        Args:
            exc_type: 発生した例外の型。
            exc: 発生した例外。
            tb: トレースバック。
        """
        self.close()

    def is_processed(self, file_path: Path) -> bool:
        """指定ファイルが記録済み（＝処理済み）かどうかを返す。

        キーを作れない場合（入力ルート外、stat 失敗など）は False を返し、
        通常どおり処理させる。判定できないことを理由に画像を取りこぼすより、
        重複して処理するほうが被害が小さい。

        Args:
            file_path: 判定対象のファイルパス。

        Returns:
            処理済みなら True。
        """
        key = self._make_key(file_path)
        if key is None:
            return False
        return key in self._keys

    def mark(self, file_path: Path) -> None:
        """指定ファイルを処理済みとして記録する。

        既に記録済みの場合は何もしない。キーを作れない場合は警告を残して
        黙って進む（1 枚の記録失敗でジョブを止めない）。

        Args:
            file_path: 記録対象のファイルパス。
        """
        key = self._make_key(file_path)
        if key is None:
            logger.warning("処理済み記録のキーを作れませんでした: %s", file_path)
            return
        if key in self._keys:
            return

        self._keys.add(key)
        self._append(key)

    def flush(self) -> None:
        """追記バッファをディスクへ書き出す。"""
        if self._handle is None:
            return
        try:
            self._handle.flush()
            self._unflushed = 0
        except OSError as exc:
            logger.error("処理済み記録の書き出しに失敗しました: %s", exc)

    def close(self) -> None:
        """記録ファイルを閉じる。二度呼んでも安全。"""
        if self._handle is None:
            return
        try:
            self._handle.flush()
            self._handle.close()
        except OSError as exc:
            logger.error("処理済み記録のクローズに失敗しました: %s", exc)
        finally:
            self._handle = None
            self._unflushed = 0

    # -----------------------------------------------------------------
    # 内部処理
    # -----------------------------------------------------------------

    def _make_key(self, file_path: Path) -> tuple[str, int, int] | None:
        """ファイルから判定キーを作る。

        Args:
            file_path: 対象のファイルパス。

        Returns:
            (相対パス, サイズ, 更新日時秒) のタプル。作れない場合は None。
        """
        try:
            relative = file_path.relative_to(self._source_root).as_posix()
        except ValueError:
            return None
        try:
            stat = file_path.stat()
        except OSError:
            return None
        return relative, stat.st_size, int(stat.st_mtime)

    def _load(self) -> None:
        """既存の記録ファイルを読み込む。

        壊れた行（強制終了で途中まで書かれた最終行など）は読み飛ばす。
        記録ファイルが無い場合は空のインデックスとして扱う。
        """
        if not self._record_path.exists():
            return

        broken = 0
        try:
            with self._record_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        self._keys.add(
                            (str(record["p"]), int(record["s"]), int(record["m"]))
                        )
                    except (ValueError, KeyError, TypeError):
                        broken += 1
        except OSError as exc:
            logger.error(
                "処理済み記録の読み込みに失敗しました: %s — %s",
                self._record_path,
                exc,
            )
            return

        if broken:
            logger.warning(
                "処理済み記録に読めない行がありました（%d 行を無視）: %s",
                broken,
                self._record_path,
            )
        logger.info(
            "処理済み記録を読み込みました: %d 件 (%s)",
            len(self._keys),
            self._record_path,
        )

    def _append(self, key: tuple[str, int, int]) -> None:
        """1 件を記録ファイルへ追記する。

        Args:
            key: 追記する判定キー。
        """
        if self._handle is None:
            try:
                self._record_path.parent.mkdir(parents=True, exist_ok=True)
                self._handle = self._record_path.open("a", encoding="utf-8")
            except OSError as exc:
                logger.error(
                    "処理済み記録を開けませんでした: %s — %s",
                    self._record_path,
                    exc,
                )
                return

        relative, size, mtime = key
        line = json.dumps(
            {"p": relative, "s": size, "m": mtime}, ensure_ascii=False
        )
        try:
            self._handle.write(line + "\n")
        except OSError as exc:
            logger.error("処理済み記録の追記に失敗しました: %s", exc)
            return

        self._unflushed += 1
        if self._unflushed >= _FLUSH_INTERVAL:
            self.flush()
