"""Connections and observations for dataset loading."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MongoConnection:
    """Connect to MongoDB without a managed deployment.

    Args:
        uri: MongoDB connection string. Can include authSource and URI credentials.
        username: Optional username passed directly to PyMongo, without URI encoding.
        password: Optional password passed directly to PyMongo, without URI encoding.

    Supplied fields override the corresponding URI credentials. Omitted fields
    retain URI settings. Credentials are excluded from repr and load reports.
    """

    uri: str = field(repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value in (self.username, self.password):
            if value is not None and not isinstance(value, str):
                raise ValueError("MongoDB username and password must be strings or None")


@dataclass(frozen=True)
class CouchbaseConnection:
    """Connect to Couchbase without a managed deployment.

    Args:
        uri: SDK connection string, including custom port mappings if needed.
        username: Account with permissions for the requested load operations.
        password: Account password. Excluded from repr and load reports.
    """

    uri: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)


@dataclass
class LoadDataResult:
    """Load progress and source information, without connection credentials.

    Counts include acknowledged writes only. A driver failure can leave additional
    writes whose outcome is unknown. Collections and index changes are not atomic.
    Attributes:
        backend: Destination backend.
        destinations: Counts by destination collection.
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
