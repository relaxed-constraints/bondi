"""Results of individual database operations."""

from dataclasses import dataclass
from typing import Any, Literal

from pymongo.errors import PyMongoError


@dataclass
class ExecutionResult:
    """Record one successful operation or a captured workload failure.

    Args:
        elapsed_ms: Client-observed monotonic elapsed time, not server execution time.
        row_count: Fully consumed document count for a successful run; otherwise None.
        documents: Collected documents when requested; otherwise None.
        explain: Raw explain response for a successful explain; otherwise None.
        error: Original exception for a failed workload entry; otherwise None.

    Partial documents and counts are discarded on failure. Exception objects are
    retained for inspection; this class does not provide persistence.
    """

    elapsed_ms: float
    row_count: int | None = None
    documents: list[dict[str, Any]] | None = None
    explain: dict[str, Any] | None = None
    error: Exception | None = None

    @property
    def status(self) -> Literal["success", "timeout", "error"]:
        """Derive status from the exception, including PyMongo's timeout flag."""
        if self.error is None:
            return "success"
        if isinstance(self.error, TimeoutError) or (
            isinstance(self.error, PyMongoError) and self.error.timeout
        ):
            return "timeout"
        return "error"
