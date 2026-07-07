"""Custom exceptions for SharipovAI OS core infrastructure."""


class SharipovAIError(Exception):
    """Base exception for all SharipovAI OS application errors.

    All custom exceptions should inherit from this class so callers can catch
    project-specific failures without catching unrelated Python exceptions.
    """


class ConfigurationError(SharipovAIError):
    """Raised when application configuration is invalid or unavailable."""


class ValidationError(SharipovAIError):
    """Raised when input validation fails inside core infrastructure."""
