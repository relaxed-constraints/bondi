"""MongoDB index definitions and synchronous creation."""

from copy import deepcopy
from dataclasses import dataclass
from typing import ClassVar

from bondi.indexes import _Definition


@dataclass
class MongoIndex(_Definition):
    """Native MongoDB ordered field index with optional constraints.

    Args:
        keys: Nonempty tuple of (field path, 1 or -1) tuples.
        name: Optional index name.
        unique: Enforce uniqueness using MongoDB semantics.
        sparse: Exclude documents using MongoDB sparse-index semantics.
        partial_filter: Native MongoDB partial predicate, copied on construction.

    Multikey indexing is automatic. Validation checks structure, not operator
    support. Special index types such as text and hashed are outside this API.
    """

    keys: tuple[tuple[str, int], ...]
    name: str | None = None
    unique: bool = False
    sparse: bool = False
    partial_filter: dict | None = None
    kind: ClassVar[str] = "mongodb"
    _options: ClassVar[tuple] = ("unique", "sparse", "partial_filter")

    def __post_init__(self):
        self.validate()
        self.partial_filter = deepcopy(self.partial_filter)

    def validate(self):
        """Validate keys and option types; reject sparse plus partial filtering."""
        super().validate()
        if type(self.unique) is not bool or type(self.sparse) is not bool:
            raise TypeError("unique and sparse must be booleans")
        if self.partial_filter is not None and not isinstance(self.partial_filter, dict):
            raise TypeError("partial_filter must be a dictionary or None")
        if self.sparse and self.partial_filter is not None:
            raise ValueError("sparse and partial_filter cannot be combined")


def create_index(connection, *, target, index, timeout=300.0):
    """Create one index and return its name after the initial build completes.

    Args:
        connection (Deployment | MongoConnection): Deployment or connection settings.
            A client is owned per call.
        target (MongoCollectionRef): MongoCollectionRef destination.
        index (FieldIndex | MongoIndex): FieldIndex or MongoIndex definition.
        timeout (float): Positive finite timeout in seconds for this operation.

    Existing-index conflicts follow MongoDB behavior. The default ascending _id
    index is reused when compatible. Errors propagate; timeouts may leave builds
    running. No indexes are dropped or replaced.
    """
    from bondi._index_creation import create_one

    return create_one("mongodb", connection, target, index, timeout)


def create_indexes(connection, *, indexes, database, timeout=300.0):
    """Create an IndexSet using one client; return collection-to-name lists.

    Args:
        connection (Deployment | MongoConnection): Deployment or MongoConnection settings.
        indexes (IndexSet): IndexSet of shared or MongoDB definitions.
        database (str): Database containing the IndexSet collections.
        timeout (float): Positive finite seconds per index, not a whole-batch deadline.

    All definitions and targets are validated before connecting. Creation is ordered
    and non-atomic. Server failures raise IndexCreationError with completed names.
    """
    from bondi._index_creation import create_many
    from bondi.indexes import IndexSet
    from bondi.mongodb.collection import MongoCollectionRef

    if not isinstance(indexes, IndexSet):
        raise TypeError("indexes must be an IndexSet")
    # Validate the namespace even when the set is empty.
    MongoCollectionRef(database, "_validation")
    targets = {name: MongoCollectionRef(database, name) for name in indexes}
    return create_many("mongodb", connection, indexes, targets, timeout)
