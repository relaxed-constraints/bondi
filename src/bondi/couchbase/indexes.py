"""Couchbase SQL++ index definitions and synchronous creation."""

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
        connection: Deployment or CouchbaseConnection settings.
        target: CouchbaseCollectionRef destination.
        index: FieldIndex or CouchbaseIndex definition.
        timeout: Positive finite seconds covering DDL and readiness waiting.

    A client is owned per call. Native expressions are executed as SQL++. Existing
    names raise server errors; no replacement or silent skipping occurs. Online
    readiness does not guarantee visibility of concurrent writes. A timeout can
    leave a build running. Requires the couchbase extra only when called.
    """
    from bondi._index_creation import create_one

    return create_one("couchbase", connection, target, index, timeout)


def create_indexes(connection, *, indexes, targets, timeout=300.0):
    """Create an IndexSet using one cluster; return target-to-name lists.

    Args:
        connection: Deployment or CouchbaseConnection settings.
        indexes: IndexSet of shared or Couchbase definitions.
        targets: Exact mapping of logical targets to CouchbaseCollectionRef objects.
        timeout: Positive finite seconds per index, not a whole-batch deadline.

    Preflight validates every definition and target before connecting. Server
    failures raise IndexCreationError with completed names. Creation is non-atomic.
    """
    from bondi._index_creation import create_many

    return create_many("couchbase", connection, indexes, targets, timeout)
