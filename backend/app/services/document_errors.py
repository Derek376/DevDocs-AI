"""Safe document errors translated to HTTP responses by the API."""

from typing import Literal


class DocumentError(ValueError):
    def __init__(
        self,
        message: str,
        kind: Literal["invalid", "unsupported", "too_large"] = "invalid",
    ) -> None:
        super().__init__(message)
        self.kind = kind
