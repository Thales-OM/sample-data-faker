class ErrorDetail:
    """Typed error detail for JSON responses"""

    def __init__(
        self,
        error_type: str,
        message: str,
        status_code: int,
        details: dict | None = None,
    ):
        self.error_type = error_type
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict"""
        result = {
            "error": self.error_type,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result

    def to_headers(self) -> dict[str, str]:
        """Convert to HTTP headers"""
        headers = {}
        return headers
