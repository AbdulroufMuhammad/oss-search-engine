from .client import APIError, AuthenticationError, RateLimitError, SeeklyClient, SeeklyError

__all__ = [
    "SeeklyClient",
    "SeeklyError",
    "AuthenticationError",
    "RateLimitError",
    "APIError",
]

__version__ = "0.1.0"
