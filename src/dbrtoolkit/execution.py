"""Results of individual database operations."""

from dataclasses import dataclass
from typing import Any, Literal

from pymongo.errors import PyMongoError


@dataclass
class ExecutionResult:
    """Record one successful operation or a captured workload failure.

    Args:
        elapsed_ms: Client-observed monotonic elapsed time, not server execution time.
        row_count: Fully consumed output-row count for a successful run; otherwise None.
        documents: Collected output rows when requested; otherwise None. Rows may be
            documents, scalars or arrays, depending on the backend.
        raw: Backend-native diagnostic response or execution metadata when available.
            Parsing is explicit; this result does not contain a QuerySummary.
        warnings: Nonfatal operation warnings; empty when none were reported.
        error: Original exception for a failed workload entry; otherwise None.

    Partial documents and counts are discarded on failure. Exception objects are
    retained for inspection; this class does not provide persistence.
    """

    elapsed_ms: float
    row_count: int | None = None
    documents: list[Any] | None = None
    raw: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
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
