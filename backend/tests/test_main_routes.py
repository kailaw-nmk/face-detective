"""main.py のルート登録に関するテスト。

プレフィックス無し (`/api/...`) と `/face-detect` 付き (`/face-detect/api/...`) の
両方で同じエンドポイントが機能することを検証する。

Tailscale Serve のパスマウント経由ではプレフィックスが剥がされて backend に届き、
M3 への直接アクセス (`http://localhost:52840`) では剥がされないため、
単一のビルド成果物で両経路を扱うには両系統を受け付ける必要がある。
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app

# プレフィックス無しと有りの両方を同じテストで検証する
PREFIXES = ["", "/face-detect"]


@pytest.fixture()
def client() -> TestClient:
    """main.app の TestClient を返す。

    Returns:
        FastAPI アプリのテストクライアント。
    """
    return TestClient(app)


@pytest.mark.parametrize("prefix", PREFIXES)
def test_validate_path_available_on_both_prefixes(
    client: TestClient, tmp_path, prefix: str,
) -> None:
    """POST /api/validate-path が両プレフィックスで応答すること。"""
    resp = client.post(
        f"{prefix}/api/validate-path", json={"path": str(tmp_path)}
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


@pytest.mark.parametrize("prefix", PREFIXES)
def test_status_available_on_both_prefixes(
    client: TestClient, prefix: str,
) -> None:
    """GET /api/status/{job_id} が両プレフィックスで応答すること。"""
    resp = client.get(f"{prefix}/api/status/no-such-job")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_found"


@pytest.mark.parametrize("prefix", PREFIXES)
def test_websocket_available_on_both_prefixes(
    client: TestClient, prefix: str,
) -> None:
    """WebSocket /ws/{job_id} が両プレフィックスで接続できること。

    未登録の job_id へ接続するとサーバーはエラーメッセージを送って切断する。
    そのメッセージを受け取れれば upgrade が成立している証拠になる。
    """
    with client.websocket_connect(f"{prefix}/ws/no-such-job") as ws:
        message = json.loads(ws.receive_text())
    assert message["type"] == "error"


_DIST_INDEX = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend"
    / "dist"
    / "index.html"
)

# dist が未ビルドの環境では静的配信テストをスキップする
_needs_dist = pytest.mark.skipif(
    not _DIST_INDEX.is_file(),
    reason="frontend/dist が未ビルドのため静的配信テストをスキップする",
)


@_needs_dist
@pytest.mark.parametrize("path", ["/", "/face-detect/"])
def test_frontend_index_served_on_both_paths(
    client: TestClient, path: str,
) -> None:
    """ビルド済みフロントの index.html が両パスで配信されること。"""
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@_needs_dist
def test_api_not_shadowed_by_static_mount(client: TestClient) -> None:
    """"/" の静的マウントが API を飲み込んでいないこと。

    StaticFiles を include_router より先に登録すると /api/* が
    静的配信に吸われて 404 になる。その登録順の回帰を検知する。
    """
    resp = client.get("/api/status/no-such-job")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_found"


def test_bare_prefix_redirects_to_index(client: TestClient) -> None:
    """末尾スラッシュ無しの /face-detect が /face-detect/ へリダイレクトすること。"""
    resp = client.get("/face-detect", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/face-detect/"


@_needs_dist
def test_bare_prefix_reaches_index_after_redirect(client: TestClient) -> None:
    """リダイレクトを追跡すると index.html に到達すること。"""
    resp = client.get("/face-detect", follow_redirects=True)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_start_accepts_trim_margins(
    client: TestClient, tmp_path, prefix: str,
) -> None:
    """POST /api/start が trim_margins を受け取り pending に保持すること。"""
    from main import job_manager

    resp = client.post(
        f"{prefix}/api/start",
        json={
            "source_folder": str(tmp_path),
            "threshold": 5.0,
            "trim_margins": True,
        },
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert job_manager._pending[job_id]["trim_margins"] is True


@pytest.mark.parametrize("prefix", PREFIXES)
def test_start_defaults_trim_margins_to_false(
    client: TestClient, tmp_path, prefix: str,
) -> None:
    """trim_margins を省略した場合は False になること（後方互換）。"""
    from main import job_manager

    resp = client.post(
        f"{prefix}/api/start",
        json={"source_folder": str(tmp_path), "threshold": 5.0},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert job_manager._pending[job_id]["trim_margins"] is False


@pytest.mark.parametrize("prefix", PREFIXES)
def test_start_accepts_dedupe(client: TestClient, tmp_path, prefix: str) -> None:
    """POST /api/start が dedupe 設定を受け取り pending に保持すること。"""
    from main import job_manager

    resp = client.post(
        f"{prefix}/api/start",
        json={
            "source_folder": str(tmp_path),
            "threshold": 5.0,
            "dedupe": True,
            "dedupe_max_distance": 4,
        },
    )

    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert job_manager._pending[job_id]["dedupe"] is True
    assert job_manager._pending[job_id]["dedupe_max_distance"] == 4


@pytest.mark.parametrize("prefix", PREFIXES)
def test_start_defaults_dedupe_to_disabled(
    client: TestClient, tmp_path, prefix: str
) -> None:
    """dedupe を省略した場合は無効・距離 0 になること（後方互換）。"""
    from main import job_manager

    resp = client.post(
        f"{prefix}/api/start",
        json={"source_folder": str(tmp_path), "threshold": 5.0},
    )

    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert job_manager._pending[job_id]["dedupe"] is False
    assert job_manager._pending[job_id]["dedupe_max_distance"] == 0
