"""ffmpeg-based video processing: iOS-compatible transcode, thumbnails, probing.

Also holds the (currently DISABLED) PornHub "Community" intro detection so it can
be re-enabled later — it is dormant because trimming forces a full re-encode that
is far too slow on long videos.
"""

import os
import asyncio
import subprocess

import numpy as np

from src.utils.logger import logger

# Intro detection (PornHub "Community" bumper) — dormant.
INTRO_SR = 16000
INTRO_MATCH_THRESHOLD = 0.45
INTRO_MAX_LEAD_IN = 1.8
INTRO_REF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "assets", "ph_community_intro.wav"
)


class VideoProcessor:
    def __init__(self):
        # Load the intro reference audio once (feature is disabled if missing).
        self._intro_ref = self._load_intro_ref()

    # --- public async API ----------------------------------------------------

    async def process(self, video_path):
        return await asyncio.to_thread(self._process, video_path)

    async def make_thumbnail(self, video_path):
        return await asyncio.to_thread(self._make_thumbnail, video_path)

    async def probe_duration(self, video_path):
        return await asyncio.to_thread(self._probe_duration, video_path)

    # --- transcode -----------------------------------------------------------

    def _process(self, video_path):
        """Transcode to H.264/AAC/yuv420p if the codec isn't iOS-friendly.

        iOS Telegram can't decode VP9/AV1 (audio plays, video freezes). H.264
        files are returned untouched (no wasteful re-encode).
        """
        # Intro removal is DISABLED: trimming forces a full re-encode which is far
        # too slow on long videos (~20 min for a 25-min clip). To re-enable,
        # restore the line below and see _detect_intro / assets/ph_community_intro.wav.
        # trim = self._detect_intro(video_path)
        trim = 0.0
        vcodec = self._probe_vcodec(video_path)
        is_h264 = vcodec.startswith("h264") or vcodec.startswith("avc")

        if trim <= 0 and is_h264:
            return video_path  # nothing to do

        out_path = os.path.splitext(video_path)[0] + "_proc.mp4"
        cmd = ["ffmpeg", "-y"]
        if trim > 0:
            cmd += ["-ss", f"{trim:.3f}"]  # precise cut requires re-encoding
        cmd += [
            "-i", video_path,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path,
        ]
        reason = []
        if trim > 0:
            reason.append(f"trim {trim:.2f}s intro")
        if not is_h264:
            reason.append(f"transcode {vcodec or 'unknown'}->h264")
        logger.info(f"Processing video ({', '.join(reason)}): {video_path}")
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                os.remove(video_path)
                logger.info(f"Processing done: {out_path}")
                return out_path
            logger.error(f"Processing produced no file for {video_path}")
        except Exception as e:
            logger.error(f"Processing failed for {video_path}: {e}")
        return video_path  # fall back to the original on failure

    def _make_thumbnail(self, video_path):
        """Extract a small JPEG frame for Telegram's video preview (<=320px, <=200KB).

        Baked into the uploaded file, so it survives in the cached file_id.
        """
        thumb_path = os.path.splitext(video_path)[0] + "_thumb.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", video_path,
                    "-vframes", "1",  # first frame
                    "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
                    thumb_path,
                ],
                check=True, capture_output=True,
            )
            if os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 0:
                logger.info(f"Generated thumbnail: {thumb_path}")
                return thumb_path
            logger.warning(f"Thumbnail not created for {video_path}")
        except Exception as e:
            logger.warning(f"Thumbnail generation failed for {video_path}: {e}")
        return None

    def _probe_vcodec(self, video_path):
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=codec_name",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path,
                ],
                check=True, capture_output=True, text=True,
            )
            return result.stdout.strip()
        except Exception as e:
            logger.warning(f"ffprobe failed for {video_path}: {e}")
            return ""

    def _probe_duration(self, video_path):
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path,
                ],
                check=True, capture_output=True, text=True,
            )
            return int(float(result.stdout.strip() or 0))
        except Exception as e:
            logger.warning(f"ffprobe duration failed for {video_path}: {e}")
            return 0

    # --- intro detection (dormant) -------------------------------------------

    def _load_intro_ref(self):
        if not os.path.isfile(INTRO_REF_PATH):
            logger.warning(f"Intro reference not found at {INTRO_REF_PATH}; intro removal disabled.")
            return None
        ref = self._decode_audio(INTRO_REF_PATH)
        if ref is None or len(ref) == 0:
            logger.warning("Intro reference failed to decode; intro removal disabled.")
            return None
        return ref

    @staticmethod
    def _decode_audio(path, duration=None, start=0.0):
        cmd = ["ffmpeg", "-v", "error", "-ss", str(start)]
        if duration:
            cmd += ["-t", str(duration)]
        cmd += ["-i", path, "-ac", "1", "-ar", str(INTRO_SR), "-f", "s16le", "-"]
        try:
            raw = subprocess.run(cmd, check=True, capture_output=True).stdout
            return np.frombuffer(raw, np.int16).astype(np.float32)
        except Exception as e:
            logger.warning(f"Audio decode failed for {path}: {e}")
            return None

    def _detect_intro(self, video_path):
        """Return seconds to trim if the PornHub bumper is at the start, else 0.0."""
        ref = self._intro_ref
        if ref is None:
            return 0.0
        ref_len_s = len(ref) / INTRO_SR
        hay = self._decode_audio(video_path, duration=ref_len_s + INTRO_MAX_LEAD_IN + 0.5)
        if hay is None or len(hay) < len(ref):
            return 0.0

        r = ref - ref.mean()
        r_norm = np.linalg.norm(r) + 1e-9
        best_corr, best_off = -1.0, 0
        step = INTRO_SR // 100  # 10ms search step
        for off in range(0, int(INTRO_MAX_LEAD_IN * INTRO_SR), step):
            seg = hay[off:off + len(ref)]
            if len(seg) < len(ref):
                break
            seg = seg - seg.mean()
            corr = float(np.dot(r, seg) / (r_norm * (np.linalg.norm(seg) + 1e-9)))
            if corr > best_corr:
                best_corr, best_off = corr, off

        if best_corr >= INTRO_MATCH_THRESHOLD:
            trim = best_off / INTRO_SR + ref_len_s
            logger.info(f"PornHub intro detected (corr={best_corr:.2f}); trimming {trim:.2f}s")
            return trim
        return 0.0
