"""face_detector モジュールの単体テスト。

detect_faces 関数の動作、返却値の構造、エラーハンドリングを検証する。
MediaPipe Tasks API をモックしてテストする。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from face_detector import detect_faces


def _make_mock_detection(width_px: int, height_px: int) -> MagicMock:
    """指定のピクセルサイズのバウンディングボックスを持つモック検出結果を生成する。"""
    bbox = MagicMock()
    bbox.width = width_px
    bbox.height = height_px
    detection = MagicMock()
    detection.bounding_box = bbox
    return detection


def _patch_detector(detections: list | None):
    """_FaceDetector.create_from_options をモックするコンテキストマネージャを返す。"""
    mock_result = MagicMock()
    mock_result.detections = detections

    mock_detector = MagicMock()
    mock_detector.detect.return_value = mock_result
    mock_detector.__enter__ = lambda self: mock_detector
    mock_detector.__exit__ = lambda self, *args: None

    return patch(
        "face_detector._FaceDetector.create_from_options",
        return_value=mock_detector,
    )


class TestDetectFacesNoFace:
    """顔が存在しない画像に対する動作を検証するテスト群。"""

    def test_detect_faces_no_face(self, sample_image: Path) -> None:
        """MediaPipe が顔を検出しなかった場合に has_face=False が返ることを確認する。"""
        with _patch_detector(detections=None):
            result = detect_faces(sample_image, threshold=10.0)

        assert result["has_face"] is False
        assert result["max_face_ratio"] == 0.0
        assert result["face_count"] == 0
        assert result["should_move"] is False

    def test_detect_faces_empty_detections(self, sample_image: Path) -> None:
        """空の detections リストが返った場合に顔なし結果が返ることを確認する。"""
        with _patch_detector(detections=[]):
            result = detect_faces(sample_image, threshold=1.0)

        assert result["has_face"] is False
        assert result["should_move"] is False


class TestDetectFacesStructure:
    """返却値の構造を検証するテスト群。"""

    def test_detect_faces_returns_correct_structure(self, sample_image: Path) -> None:
        """すべての必須キーが結果辞書に含まれていることを確認する。"""
        with _patch_detector(detections=None):
            result = detect_faces(sample_image, threshold=10.0)

        assert "has_face" in result
        assert "max_face_ratio" in result
        assert "face_count" in result
        assert "should_move" in result

    def test_detect_faces_result_types(self, sample_image: Path) -> None:
        """各フィールドの型が仕様通りであることを確認する。"""
        with _patch_detector(detections=None):
            result = detect_faces(sample_image, threshold=10.0)

        assert isinstance(result["has_face"], bool)
        assert isinstance(result["max_face_ratio"], float)
        assert isinstance(result["face_count"], int)
        assert isinstance(result["should_move"], bool)

    def test_detect_faces_ratio_is_nonnegative(self, sample_image: Path) -> None:
        """max_face_ratio が常に 0 以上であることを確認する。"""
        with _patch_detector(detections=None):
            result = detect_faces(sample_image, threshold=5.0)

        assert result["max_face_ratio"] >= 0.0


class TestDetectFacesWithMockedDetection:
    """MediaPipe をモックして顔検出ロジックを検証するテスト群。"""

    def test_above_threshold(self, sample_image: Path) -> None:
        """面積比が閾値以上の場合に should_move=True が返ることを確認する。

        200x200 画像 (面積=40000) に対し、100x100 px の顔
        (面積=10000) → 面積比25% で threshold=20 なら should_move=True。
        """
        detection = _make_mock_detection(100, 100)
        with _patch_detector(detections=[detection]):
            result = detect_faces(sample_image, threshold=20.0)

        assert result["has_face"] is True
        assert result["face_count"] == 1
        assert abs(result["max_face_ratio"] - 25.0) < 0.01
        assert result["should_move"] is True

    def test_below_threshold(self, sample_image: Path) -> None:
        """面積比が閾値未満の場合に should_move=False が返ることを確認する。

        200x200 画像で 20x20 px の顔 → 面積比1% で threshold=5 なら should_move=False。
        """
        detection = _make_mock_detection(20, 20)
        with _patch_detector(detections=[detection]):
            result = detect_faces(sample_image, threshold=5.0)

        assert result["has_face"] is True
        assert result["should_move"] is False

    def test_selects_largest_face(self, sample_image: Path) -> None:
        """複数の顔が検出された場合、最大の顔の面積比が使われることを確認する。

        小さい顔（20x20px）と大きい顔（80x80px=6400px²）→ 面積比16%。
        """
        small = _make_mock_detection(20, 20)
        large = _make_mock_detection(80, 80)
        with _patch_detector(detections=[small, large]):
            result = detect_faces(sample_image, threshold=5.0)

        assert result["face_count"] == 2
        assert abs(result["max_face_ratio"] - 16.0) < 0.01

    def test_threshold_boundary_equal(self, sample_image: Path) -> None:
        """面積比が閾値と等しい場合に should_move=True が返ることを確認する。"""
        # 200x200=40000 の画像で 40x50=2000 → 5%
        detection = _make_mock_detection(40, 50)
        with _patch_detector(detections=[detection]):
            result = detect_faces(sample_image, threshold=5.0)

        assert result["should_move"] is True


class TestDetectFacesErrorHandling:
    """エラーハンドリングを検証するテスト群。"""

    def test_invalid_image(self, tmp_path: Path) -> None:
        """破損したファイルを渡した場合に例外を送出せず顔なし結果が返ることを確認する。"""
        corrupted = tmp_path / "corrupted.png"
        corrupted.write_bytes(b"this is not a valid image file at all!!")

        result = detect_faces(corrupted, threshold=10.0)

        assert result["has_face"] is False
        assert result["max_face_ratio"] == 0.0
        assert result["should_move"] is False

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """存在しないファイルを渡した場合に例外を送出せず顔なし結果が返ることを確認する。"""
        result = detect_faces(tmp_path / "missing.jpg", threshold=10.0)

        assert result["has_face"] is False
        assert result["should_move"] is False

    def test_does_not_raise_on_error(self, tmp_path: Path) -> None:
        """任意のエラーが発生しても detect_faces が例外を送出しないことを確認する。"""
        bad_file = tmp_path / "bad.jpg"
        bad_file.write_bytes(b"\xff\xd8\xff")

        try:
            detect_faces(bad_file, threshold=10.0)
        except Exception as exc:
            pytest.fail(f"detect_faces が予期しない例外を送出しました: {exc}")

    def test_mediapipe_exception_handled(self, sample_image: Path) -> None:
        """MediaPipe 処理中に例外が発生した場合も顔なし結果が返ることを確認する。"""
        with patch(
            "face_detector._FaceDetector.create_from_options",
            side_effect=RuntimeError("MediaPipe error"),
        ):
            result = detect_faces(sample_image, threshold=10.0)

        assert result["has_face"] is False
        assert result["should_move"] is False
