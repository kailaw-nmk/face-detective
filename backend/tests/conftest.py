"""pytest 共有フィクスチャ定義。

テスト全体で使用する一時ディレクトリと画像サンプルのフィクスチャを提供する。
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

# backend/ ディレクトリをインポートパスに追加する
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# MediaPipe スタブ
# ---------------------------------------------------------------------------
# テスト環境では MediaPipe Tasks API のスタブを差し込み、
# face_detector.py がモデルファイルなしでもインポートできるようにする。
# 個々のテストでは face_detector 内の変数を直接パッチする。
# ---------------------------------------------------------------------------
_mp_stub = types.ModuleType("mediapipe")

# mp.ImageFormat / mp.Image
_mp_stub.ImageFormat = MagicMock()  # type: ignore[attr-defined]
_mp_stub.ImageFormat.SRGB = "SRGB"
_mp_stub.Image = MagicMock()  # type: ignore[attr-defined]

# mp.tasks.BaseOptions
_tasks_stub = types.ModuleType("mediapipe.tasks")
_tasks_stub.BaseOptions = MagicMock()  # type: ignore[attr-defined]

# mp.tasks.vision.FaceDetector / FaceDetectorOptions
_vision_stub = types.ModuleType("mediapipe.tasks.vision")
_vision_stub.FaceDetector = MagicMock()  # type: ignore[attr-defined]
_vision_stub.FaceDetectorOptions = MagicMock()  # type: ignore[attr-defined]

_tasks_stub.vision = _vision_stub  # type: ignore[attr-defined]
_mp_stub.tasks = _tasks_stub  # type: ignore[attr-defined]

sys.modules["mediapipe"] = _mp_stub
sys.modules["mediapipe.tasks"] = _tasks_stub
sys.modules["mediapipe.tasks.vision"] = _vision_stub

# ---------------------------------------------------------------------------
# pillow-heif スタブ
# ---------------------------------------------------------------------------
# テスト環境では pillow-heif がインストールされていない場合があるため、
# 必要最低限のスタブを差し込む。
# ---------------------------------------------------------------------------
if "pillow_heif" not in sys.modules:
    _heif_stub = types.ModuleType("pillow_heif")
    _heif_stub.register_heif_opener = lambda: None  # type: ignore[attr-defined]
    sys.modules["pillow_heif"] = _heif_stub

# ---------------------------------------------------------------------------
# ultralytics スタブ
# ---------------------------------------------------------------------------
if "ultralytics" not in sys.modules:
    _ultra_stub = types.ModuleType("ultralytics")
    _ultra_stub.YOLO = MagicMock()  # type: ignore[attr-defined]
    sys.modules["ultralytics"] = _ultra_stub


@pytest.fixture()
def tmp_source_dir(tmp_path: Path) -> Path:
    """画像ファイルが含まれた一時ソースディレクトリを返す。

    Returns:
        一時ソースディレクトリのパス。
    """
    source = tmp_path / "source"
    source.mkdir()
    return source


@pytest.fixture()
def tmp_dest_dir(tmp_path: Path) -> Path:
    """空の一時移動先ディレクトリを返す。

    Returns:
        一時移動先ディレクトリのパス。
    """
    dest = tmp_path / "dest"
    dest.mkdir()
    return dest


@pytest.fixture()
def sample_image(tmp_path: Path) -> Path:
    """200x200 の単色 PNG 画像を作成して返す。

    Returns:
        作成した画像ファイルのパス。
    """
    image_path = tmp_path / "sample.png"
    img = Image.new("RGB", (200, 200), color=(128, 128, 128))
    img.save(image_path)
    return image_path


@pytest.fixture()
def sample_image_with_face(tmp_path: Path) -> Path:
    """400x400 の肌色領域を持つ PNG 画像を作成して返す。

    顔検出の単体テストではモックを使用するため、
    ここでは構造上リアルな画像サイズを持つ単純な画像で十分である。

    Returns:
        作成した画像ファイルのパス。
    """
    image_path = tmp_path / "sample_with_face.png"
    img = Image.new("RGB", (400, 400), color=(255, 220, 185))
    img.save(image_path)
    return image_path
