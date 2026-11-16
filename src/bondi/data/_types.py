"""Connections and observations for dataset loading."""

from dataclasses import dataclass, field
from typing import Any

from bondi.connection import CouchbaseConnection, MongoConnection  # noqa: F401


@dataclass
class LoadDataResult:
    """Load progress and source information, without connection credentials.

    Counts include acknowledged writes only. A driver failure can leave additional
    writes whose outcome is unknown. Collection changes are not atomic.
    Attributes:
        backend: Destination backend.
        destinations: Counts keyed by database.collection for MongoDB or
            bucket.scope.collection for Couchbase.
        source_counts: Counts by logical collection and original split.
        conversions: Counts of converted values by type.
        sources: Source revisions and file identities.
        settings: ID, split, write and type rules used for the load.
        elapsed_seconds: Time since loading began, including preparation.
        uncertain_writes: True if a write failed without an exact outcome.
    """

    backend: str
    destinations: dict[str, int] = field(default_factory=dict)
    source_counts: dict[str, int] = field(default_factory=dict)
    conversions: dict[str, int] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0
    uncertain_writes: bool = False


class LoadDataError(RuntimeError):
    """Load failure with a partial result.

    Attributes:
        result: Progress recorded before failure. Some writes may be uncertain.
    """

    def __init__(self, message: str, result: LoadDataResult):
        super().__init__(message)
        self.result = result
