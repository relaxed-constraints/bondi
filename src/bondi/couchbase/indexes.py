"""Couchbase SQL++ index definitions and synchronous lifecycle operations."""

from dataclasses import dataclass
from typing import ClassVar

from bondi.indexes import _Definition


@dataclass
class CouchbaseIndex(_Definition):
    """Native SQL++ expressions with optional partial and missing-key behavior.

    Args:
        keys: Nonempty tuple of (trusted SQL++ expression, 1 or -1) tuples.
        name: Optional server index name.
        condition: Trusted SQL++ partial-index predicate, or None.
        include_missing: Include missing leading-key values.

    Expressions and predicates are native executable SQL++, not escaped field
    paths. Only use trusted definitions. Array indexes use native array expressions.
    Server syntax and expression compatibility are not validated offline.
    """

    keys: tuple[tuple[str, int], ...]
    name: str | None = None
    condition: str | None = None
    include_missing: bool = False
    kind: ClassVar[str] = "couchbase"
    _options: ClassVar[tuple] = ("condition", "include_missing")

    def __post_init__(self):
        self.validate()

    def validate(self):
        """Validate keys and option structure without parsing SQL++."""
        super().validate()
        if type(self.include_missing) is not bool:
            raise TypeError("include_missing must be boolean")
        if self.condition is not None and (
            not isinstance(self.condition, str)
            or not self.condition.strip()
            or "\0" in self.condition
        ):
            raise ValueError("condition must be nonempty SQL++ or None")


def create_index(connection, *, target, index, timeout=300.0):
    """Create an index, wait until online and return its name.

    Args:
        connection (Deployment | CouchbaseConnection): Deployment or CouchbaseConnection settings.
        target (CouchbaseCollectionRef): CouchbaseCollectionRef destination.
        index (FieldIndex | CouchbaseIndex): FieldIndex or CouchbaseIndex definition.
        timeout (float): Positive finite seconds covering DDL and readiness waiting.

    A client is owned per call. Native expressions are executed as SQL++. Existing
    names raise server errors; no replacement or silent skipping occurs. Online
    readiness does not guarantee visibility of concurrent writes. A timeout can
    leave a build running. Requires the couchbase extra only when called.
    """
    from bondi._index_creation import create_one

    return create_one("couchbase", connection, target, index, timeout)


def create_indexes(connection, *, indexes, bucket, scope, timeout=300.0, replace=False):
    """Create an IndexSet using one cluster; return collection-to-name lists.

    Args:
        connection (Deployment | CouchbaseConnection): Deployment or CouchbaseConnection settings.
        indexes (IndexSet): IndexSet of shared or Couchbase definitions.
        bucket (str): Bucket containing the IndexSet collections.
        scope (str): Scope containing the IndexSet collections.
        timeout (float): Positive finite seconds per inspection, removal or creation operation.
        replace (bool): Remove all secondary indexes on included collections before creation.
            Preserve primary indexes; empty collection lists clear secondary indexes.

    Preflight validates every definition and target before connecting. Server
    failures raise IndexCreationError with completed names. Creation is non-atomic.
    Replacement includes indexes created outside BONDI, leaves omitted collections
    untouched and is non-atomic. Inspect all collections, then remove, then create.
    IndexCreationError reports the failing phase, confirmed removals and creations.
    No rollback is attempted. Run without concurrent index administration.
    """
    from bondi._index_creation import create_many
    from bondi.couchbase.collection import CouchbaseCollectionRef
    from bondi.indexes import IndexSet

    if not isinstance(indexes, IndexSet):
        raise TypeError("indexes must be an IndexSet")
    # Validate the namespace even when the set is empty.
    CouchbaseCollectionRef(bucket, scope, "_validation")
    targets = {name: CouchbaseCollectionRef(bucket, scope, name) for name in indexes}
    return create_many("couchbase", connection, indexes, targets, timeout, replace)


def remove_index(connection, *, target, index, timeout=300.0):
    """Remove one named index; return True if removed, False if already absent.

    Args:
        connection (Deployment | CouchbaseConnection): Deployment or connection settings.
        target (CouchbaseCollectionRef): Destination collection.
        index (FieldIndex | CouchbaseIndex): Definition identifying an explicit or generated name.
        timeout (float): Positive finite seconds per inspection or removal operation.

    Removal matches names only, not keys/options. Protected primary indexes raise
    ValueError. Other native errors propagate. The owned client always closes.
    """
    from bondi._index_creation import remove_one

    return remove_one("couchbase", connection, target, index, timeout)


def remove_indexes(connection, *, indexes, bucket, scope, timeout=300.0):
    """Remove named definitions; return collection-to-removed-name lists.

    Args:
        connection (Deployment | CouchbaseConnection): Deployment or connection settings.
        indexes (IndexSet): Definitions identifying explicit or generated names.
        bucket (str): Bucket containing the IndexSet collections.
        scope (str): Scope containing the IndexSet collections.
        timeout (float): Positive finite seconds per inspection or removal operation.

    Missing names are skipped. Empty lists remove nothing. Only named definitions
    are removed, regardless of their keys/options. Protected primary indexes raise
    ValueError before any deletion. Validation precedes connection; inspection
    precedes removal. One client is owned per call. Server failures raise
    IndexRemovalError with completed removals; no rollback is attempted.
    """
    from bondi._index_creation import remove_many
    from bondi.couchbase.collection import CouchbaseCollectionRef
    from bondi.indexes import IndexSet

    if not isinstance(indexes, IndexSet):
        raise TypeError("indexes must be an IndexSet")
    CouchbaseCollectionRef(bucket, scope, "_validation")
    targets = {name: CouchbaseCollectionRef(bucket, scope, name) for name in indexes}
    return remove_many("couchbase", connection, indexes, targets, timeout)
