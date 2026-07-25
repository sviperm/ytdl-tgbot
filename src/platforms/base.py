"""Platform strategy interface."""

from abc import ABC, abstractmethod


class Platform(ABC):
    name = "platform"

    @abstractmethod
    def matches(self, url):
        """True if this platform handles the given URL."""

    @abstractmethod
    async def probe(self, url):
        """Return cheap PostMeta for the cache check. May raise PlatformError."""

    @abstractmethod
    async def fetch(self, url, meta, status, work_dir):
        """Download + process media into a Post. May raise PlatformError.

        Every file must be written inside ``work_dir``: it belongs to this request
        alone and the orchestrator deletes the whole tree afterwards, so nothing
        collides with a concurrent request and nothing leaks when this raises.

        Returns a Post whose ``meta`` is the final metadata — refine ``meta`` with
        ``dataclasses.replace`` rather than mutating it, so probe's result stays
        reproducible.
        """
