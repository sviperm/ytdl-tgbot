"""Environment probes shared by the opt-in live test tiers.

A live test may only go red when the *code* is wrong. Missing infrastructure — no
PO-token provider, no deno, an unreachable third-party host, no dev-bot
credentials — is an environment gap, so it skips with a reason. Without that
split the opt-in run becomes noise nobody reads, and a real regression hides in it.
"""

import shutil
import socket
from urllib.parse import urlsplit

import pytest

from src.config import Config


def tcp_reachable(url, timeout=2):
    """Whether a TCP connection to the URL's host:port opens at all."""
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


def skip_unless_youtube_env_ready():
    """YouTube needs the PO-token provider and Deno to reach 1080p at all."""
    if not shutil.which("deno"):
        pytest.skip("YouTube needs deno on PATH to solve the JS challenge")
    if not tcp_reachable(Config.POT_PROVIDER_URL):
        pytest.skip(
            f"YouTube needs the PO-token provider at {Config.POT_PROVIDER_URL} "
            "(docker compose up -d pot-provider)"
        )


def skip_unless_ffmpeg():
    """ffmpeg/ffprobe build the synthetic media the upload tests send."""
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            pytest.skip(f"{tool} is needed to generate test media")
