class URLValidationError(ValueError):
    """Raised when a URL fails syntactic validation or SSRF checks."""


class SSRFError(URLValidationError):
    """Raised when a hostname resolves to a blocked IP or cannot be resolved safely.

    Subclasses ``URLValidationError`` so existing callers that catch
    ``URLValidationError`` continue to treat DNS-level rejections as validation
    failures.
    """
