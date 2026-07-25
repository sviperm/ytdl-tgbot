"""Platform errors that carry the exact user-facing message.

The orchestrator maps any PlatformError to a status update via ``user_message``,
so platforms decide the wording and the orchestrator stays generic.
"""


class PlatformError(Exception):
    def __init__(self, message, user_message):
        super().__init__(message)
        self.user_message = user_message


class ExtractError(PlatformError):
    """Metadata extraction failed for a reason other than authentication."""

    def __init__(self, message="metadata extraction failed",
                 user_message="Failed to extract video info. Are you sure the link is valid?"):
        super().__init__(message, user_message)


class AuthRequiredError(PlatformError):
    """The post is login-gated (Instagram etc.)."""

    def __init__(self, message="authentication required",
                 user_message=("🔒 This post requires login (e.g. Instagram now needs it) "
                               "and can't be downloaded without an authenticated cookies file.")):
        super().__init__(message, user_message)


class DownloadError(PlatformError):
    def __init__(self, message="download failed", user_message="Download failed."):
        super().__init__(message, user_message)


class FetchError(PlatformError):
    """Instagram post could not be fetched."""

    def __init__(self, message="fetch failed",
                 user_message=("🔒 Couldn't fetch this Instagram post. It may be private/deleted, "
                               "or its video is login-gated from this server's IP.")):
        super().__init__(message, user_message)
