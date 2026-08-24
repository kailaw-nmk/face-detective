"""配信する frontend/dist の base パス検査に関するテスト。

素の ``npm run build`` で作られた dist は ``/assets/...`` を参照するため、
``localhost:52840`` では動くのに Tailscale Serve の ``/face-detect/`` 経由
だけ真っ白になる。起動時にこれを検知して警告するためのロジックを検証する。
"""

from pathlib import Path

from main import check_dist_base_path

# プレフィックス付きで正しくビルドされた index.html
_PREFIXED_HTML = (
    "<!doctype html><html><head>"
    '<script type="module" crossorigin '
    'src="/face-detect/assets/index-abc.js"></script>'
    "</head><body><div id=\"root\"></div></body></html>"
)

# 素の npm run build で作られた index.html
_ROOT_HTML = (
    "<!doctype html><html><head>"
    '<script type="module" crossorigin src="/assets/index-abc.js"></script>'
    "</head><body><div id=\"root\"></div></body></html>"
)


def _write_dist(tmp_path: Path, html: str) -> Path:
    """index.html を持つ dist ディレクトリを作る。

    Args:
        tmp_path: pytest の一時ディレクトリ。
        html: 書き込む index.html の内容。

    Returns:
        作成した dist ディレクトリのパス。
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(html, encoding="utf-8")
    return dist


def test_returns_none_for_prefixed_build(tmp_path: Path) -> None:
    """プレフィックス付きのビルドなら警告を返さないこと。"""
    dist = _write_dist(tmp_path, _PREFIXED_HTML)

    assert check_dist_base_path(dist) is None


def test_warns_for_root_build(tmp_path: Path) -> None:
    """素のビルドなら警告文言を返すこと。"""
    dist = _write_dist(tmp_path, _ROOT_HTML)

    warning = check_dist_base_path(dist)

    assert warning is not None
    assert "/face-detect/" in warning


def test_warning_mentions_how_to_rebuild(tmp_path: Path) -> None:
    """警告に再ビルド方法が含まれること。

    原因だけ告げて直し方を書かないと、警告を読んでも手が止まる。
    """
    dist = _write_dist(tmp_path, _ROOT_HTML)

    warning = check_dist_base_path(dist)

    assert warning is not None
    assert "npm run build" in warning


def test_returns_none_when_index_is_missing(tmp_path: Path) -> None:
    """index.html が無い場合は警告を返さないこと。

    未ビルドは別の警告が担当するため、ここで二重に警告しない。
    """
    dist = tmp_path / "dist"
    dist.mkdir()

    assert check_dist_base_path(dist) is None
