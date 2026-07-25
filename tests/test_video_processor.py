import os
import subprocess

import pytest

from src.services.video import VideoProcessor


@pytest.fixture
def processor(monkeypatch):
    # Skip loading the intro reference wav during construction.
    monkeypatch.setattr(VideoProcessor, "_load_intro_ref", lambda self: None)
    return VideoProcessor()


def test_h264_returned_untouched(processor, monkeypatch, tmp_path):
    monkeypatch.setattr(processor, "_probe_vcodec", lambda p: "h264")
    spawned = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: spawned.append(a))
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    out = processor._process(str(src))
    assert out == str(src)
    assert spawned == []  # no ffmpeg spawned for already-h264


def test_vp9_transcoded_to_h264(processor, monkeypatch, tmp_path):
    monkeypatch.setattr(processor, "_probe_vcodec", lambda p: "vp9")
    src = tmp_path / "v.webm.mp4"
    src.write_bytes(b"x")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        out = os.path.splitext(str(src))[0] + "_proc.mp4"
        open(out, "wb").write(b"transcoded")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = processor._process(str(src))
    assert out.endswith("_proc.mp4")
    cmd = captured["cmd"]
    for token in ("libx264", "yuv420p", "aac", "+faststart"):
        assert token in cmd
    assert "-ss" not in cmd  # intro trim disabled -> no seek
    assert not os.path.exists(str(src))  # original removed


def test_probe_duration_parses(processor, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="27.35\n", stderr=""),
    )
    assert processor._probe_duration("x.mp4") == 27


def test_make_thumbnail_argv(processor, monkeypatch, tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        open(os.path.splitext(str(src))[0] + "_thumb.jpg", "wb").write(b"jpg")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = processor._make_thumbnail(str(src))
    assert out.endswith("_thumb.jpg")
    assert "-vframes" in captured["cmd"] and "1" in captured["cmd"]
    assert any("scale=320" in tok for tok in captured["cmd"])
