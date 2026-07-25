"""Platform strategy interface."""

from abc import ABC, abstractmethod


class Platform(ABC):
    name = "platform"
    initial_status = "Working..."

    @abstractmethod
    def matches(self, url):
        """True if this platform handles the given URL."""

    @abstractmethod
    async def probe(self, url):
        """Return cheap PostMeta for the cache check. May raise PlatformError."""

    @abstractmethod
    async def fetch(self, url, meta, status):
        """Download + process media into a Post. May raise PlatformError."""
