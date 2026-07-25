"""Picks the platform for a URL. Order matters — Generic must be last."""


class PlatformRegistry:
    def __init__(self, platforms):
        self._platforms = platforms

    @property
    def platforms(self):
        """Registered platforms in resolution order (read-only view)."""
        return tuple(self._platforms)

    def resolve(self, url):
        for platform in self._platforms:
            if platform.matches(url):
                return platform
        return None
