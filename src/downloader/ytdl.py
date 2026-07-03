import yt_dlp
import asyncio
import os
import re
import subprocess
import numpy as np
from src.config import Config

from src.utils.logger import logger

# Intro detection (PornHub "Community" bumper) --------------------------------
# The bumper is a fixed clip prepended to some videos; we detect it by matching
# its audio fingerprint against the start of the download and trim it off.
INTRO_SR = 16000                 # mono sample rate used for correlation
INTRO_MATCH_THRESHOLD = 0.45     # normalized cross-correlation cutoff (pos ~0.55-1.0, neg <0.05)
INTRO_MAX_LEAD_IN = 1.8          # seconds of start offset to search for the bumper
INTRO_REF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "assets", "ph_community_intro.wav"
)


class Downloader:
    """Wrapper for yt-dlp to extract info and download videos asynchronously."""

    def __init__(self):
        # Check if ffmpeg is available
        import shutil
        if not shutil.which("ffmpeg"):
            logger.error("FFmpeg not found! High-quality downloads will fail. Please install ffmpeg.")

        # Load the intro reference audio once (feature is disabled if missing).
        self._intro_ref = self._load_intro_ref()

        # Last extraction error message, so the handler can craft a useful reply.
        self.last_extract_error = None

        self.ydl_opts = {
            # Prefer H.264 (avc1) + AAC: the only codecs iOS/Telegram play everywhere
            # (VP9/AV1 freeze on iOS). Anything else is transcoded after download.
            # Capped at 1080p on the long edge so vertical/shorts keep full resolution.
            # `<=?` keeps formats whose dimensions are unknown (e.g. some non-YouTube sites).
            'format': (
                'bestvideo[vcodec^=avc1][width<=?1920][height<=?1920]+bestaudio[acodec^=mp4a]/'
                'bestvideo[vcodec^=avc1][width<=?1920][height<=?1920]+bestaudio/'
                'bestvideo[width<=?1920][height<=?1920][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[width<=?1920][height<=?1920]+bestaudio/'
                'best[width<=?1920][height<=?1920]/best'
            ),
            'outtmpl': os.path.join(Config.DOWNLOAD_DIR, '%(id)s.%(ext)s'),
            'cookiefile': Config.COOKIES_FILE if os.path.isfile(Config.COOKIES_FILE) else None,
            # 'quiet': True,
            # 'no_warnings': True,
            'extractor_args': {
                # Let yt-dlp use its current default YouTube clients (tv/web_safari) and
                # fetch GVS PO tokens from the bgutil HTTP provider to unlock 1080p.
                'youtubepot-bgutilhttp': {
                    'base_url': [Config.POT_PROVIDER_URL],
                },
            },
        }

    @staticmethod
    def _normalize_url(url):
        """Rewrite URLs that yt-dlp mis-classifies.

        A PornHub 'shorties/<id>' link is caught by the paged-list extractor and
        yields an empty playlist; the single-video form downloads correctly.
        """
        m = re.match(r'https?://(?:www\.)?pornhub\.com/shorties/([0-9a-zA-Z]+)', url)
        if m:
            return f'https://www.pornhub.com/view_video.php?viewkey={m.group(1)}'
        return url

    async def extract_info(self, url):
        return await asyncio.to_thread(self._extract_info, self._normalize_url(url))

    def _apply_cookies(self):
        """Pick up data/cookies.txt live, so it can be added/refreshed without a restart."""
        self.ydl_opts['cookiefile'] = (
            Config.COOKIES_FILE if os.path.isfile(Config.COOKIES_FILE) else None
        )

    def _extract_info(self, url):
        self.last_extract_error = None
        self._apply_cookies()
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                logger.info(f"Extracting metadata for: {url}")
                info = ydl.extract_info(url, download=False)
                return info
            except Exception as e:
                self.last_extract_error = str(e)
                logger.error(f"Error during metadata extraction for {url}: {e}")
                return None

    async def download(self, url):
        return await asyncio.to_thread(self._download, self._normalize_url(url))

    def _download(self, url):
        self._apply_cookies()
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                logger.info(f"Starting actual download for: {url}")
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                # If it's a merged file, the extension might change
                if not os.path.exists(filename):
                    # Try to find the file with any extension but same id
                    base = os.path.splitext(filename)[0]
                    for f in os.listdir(Config.DOWNLOAD_DIR):
                        if f.startswith(os.path.basename(base)):
                            filename = os.path.join(Config.DOWNLOAD_DIR, f)
                            break

                if os.path.exists(filename):
                    logger.info(f"File downloaded successfully to: {filename}")
                else:
                    logger.error(f"Download reported success but file not found: {filename}")

                return filename, info
            except Exception as e:
                logger.error(f"Error during download for {url}: {e}")
                return None, None

    async def make_thumbnail(self, video_path):
        return await asyncio.to_thread(self._make_thumbnail, video_path)

    def _make_thumbnail(self, video_path):
        """Extract a small JPEG frame for Telegram's video preview.

        Telegram bakes the supplied thumb into the uploaded file, so it is
        preserved in the cached file_id and shows up on later cache hits.
        Must be JPEG, <=200KB and <=320px on the longest side.
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
                check=True,
                capture_output=True,
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

    async def probe_duration(self, video_path):
        return await asyncio.to_thread(self._probe_duration, video_path)

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

    # --- Intro (PornHub Community bumper) detection ---------------------------

    def _load_intro_ref(self):
        """Decode the bundled bumper reference to a mono float array (or None)."""
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
        """Decode audio to a mono float32 numpy array at INTRO_SR via ffmpeg."""
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
        """Return seconds to trim if the PornHub bumper is at the start, else 0.0.

        Matches the reference bumper audio against the first few seconds of the
        video via normalized cross-correlation, allowing a small lead-in offset.
        """
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

    # --- Post-download processing (intro trim + iOS-compatible codec) ---------

    async def process_video(self, video_path):
        return await asyncio.to_thread(self._process_video, video_path)

    def _process_video(self, video_path):
        """Trim a detected intro and/or transcode to H.264 for iOS playback.

        Runs in a single ffmpeg pass. If there's no intro to trim and the codec
        is already H.264, the file is returned untouched (no wasteful re-encode).
        """
        trim = self._detect_intro(video_path)
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
