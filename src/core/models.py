"""Domain models shared across platforms, services, and the orchestrator."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MediaItem:
    """A single downloaded media file ready to send."""

    kind: str            # "video" or "image"
    path: str            # local file path
    thumb: Optional[str] = None  # local thumbnail path (videos only)


@dataclass
class PostMeta:
    """Cheap metadata produced by ``Platform.probe`` for the cache check.

    Carries the finished HTML ``caption_html`` so the sender/orchestrator stay
    platform-agnostic. ``supports_cache`` is True only for single yt-dlp videos.
    """

    video_id: Optional[str] = None
    platform: Optional[str] = None
    title: Optional[str] = None
    caption_html: str = ""
    duration: int = 0
    width: int = 0
    height: int = 0
    supports_cache: bool = False


@dataclass
class Post:
    """A fully-prepared post: metadata + downloaded local media items."""

    meta: PostMeta
    media: List[MediaItem] = field(default_factory=list)
    use_upload_progress: bool = False       # yt-dlp True, Instagram False
    upload_status_text: str = "Uploading..."

    def all_paths(self):
        """Every local path to clean up after sending (media + thumbnails)."""
        paths = []
        for item in self.media:
            if item.path:
                paths.append(item.path)
            if item.thumb:
                paths.append(item.thumb)
        return paths
