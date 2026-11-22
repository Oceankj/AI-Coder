# Author: Ching Kao
# Student ID: 85768427
"""Safe errors exposed by the common model-call boundary."""


class LLMError(Exception):
    def __init__(self, status: int, code: str, message: str, *, metadata: dict | None = None):
        super().__init__(message)
        self.status, self.code = status, code
        self.metadata = metadata or {}
