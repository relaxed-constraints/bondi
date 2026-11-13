"""Logical Couchbase collection identifiers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CouchbaseCollectionRef:
    """Identify a Couchbase collection without opening a connection.

    Names are preserved exactly. Empty names and null characters are rejected.
    The server can impose additional naming restrictions.

    Args:
        bucket: Bucket name.
        scope: Scope name.
        collection: Collection name.
    """

    bucket: str
    scope: str
    collection: str

    def __post_init__(self):
        for field in ("bucket", "scope", "collection"):
            value = getattr(self, field)
            if not isinstance(value, str):
                raise TypeError(f"{field} must be a string")
            if not value or "\0" in value:
                raise ValueError(f"{field} must be nonempty and contain no null characters")
