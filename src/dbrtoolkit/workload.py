"""Ordered, single-backend workloads with explicit reference semantics."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import overload

from dbrtoolkit.query import Query


@dataclass
class WorkloadEntry:
    """Associate a query reference with optional local pattern membership.

    The query is retained by reference, not copied. Multiple entries may share
    one query; edits to that query are visible through all of them. This mutable
    entry is unhashable. Later assignments are ordinary Python mutations.

    Args:
        query: Object exposing the Query contract. Validation calls its validate
            method but does not serialize, fingerprint or execute it.
        pattern_id: Nonnegative integer identifier, or None. Booleans are rejected.
            The identifier is local to the originating workload/pattern collection,
            not a list position or globally unique ID. No pattern registry is checked.

    Raises:
        TypeError: Query members are missing or pattern_id has an incorrect type.
        ValueError: Backend is blank or pattern_id is negative.

    Query-specific validation errors also propagate.
    """

    query: Query
    pattern_id: int | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate current query and metadata without copying or modifying either.

        Raises:
            TypeError: Query contract members or pattern_id have incorrect types.
            ValueError: Backend is blank or pattern_id is negative.

        Query validation errors propagate unchanged. Runtime member checks verify
        availability, not signatures or the semantics of custom implementations.
        """
        backend = getattr(self.query, "backend", None)
        if not isinstance(backend, str):
            raise TypeError("query.backend must be a string")
        if not backend.strip():
            raise ValueError("query.backend must not be blank")
        for name in ("validate", "to_json", "fingerprint"):
            if not callable(getattr(self.query, name, None)):
                raise TypeError(f"query must provide a callable {name} method")
        if self.pattern_id is not None:
            if type(self.pattern_id) is not int:
                raise TypeError("pattern_id must be an integer or None, not a boolean")
            if self.pattern_id < 0:
                raise ValueError("pattern_id must be nonnegative")
        self.query.validate()


@dataclass
class Workload:
    """Organize ordered query entries for one database backend.

    Copies the supplied list shallowly at construction, retaining entry and query
    references. Order and duplicate entries are preserved. Adding/removing items
    in the caller's list does not affect the workload, but editing shared entries
    or queries does. Use copy.deepcopy explicitly for independent contents.

    Same-backend validation permits MongoDB find and aggregation queries together,
    including different named databases/collections. It rejects mixing MongoDB and
    Couchbase. An empty workload is valid and has no backend restriction until
    populated. The rule is checked at construction and on validate(), not on edits.

    Args:
        entries: List of WorkloadEntry references. Defaults to an independent empty list.

    Raises:
        TypeError: Entries is not a list or contains a non-WorkloadEntry object.
        ValueError: Entries have different query backend identifiers.

    Entry and query validation errors also propagate. No generation, execution,
    persistence, weights or pattern-registry management is provided yet.

    Examples:
        >>> from dbrtoolkit.mongodb import MongoCollectionRef, MongoFindQuery
        >>> query = MongoFindQuery(MongoCollectionRef("research", "businesses"), {})
        >>> workload = Workload([WorkloadEntry(query, pattern_id=0)])
        >>> query.limit = 10
        >>> workload[0].query.limit
        10
        >>> len(workload)
        1
    """

    entries: list[WorkloadEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.validate()
        self.entries = list(self.entries)

    def validate(self) -> None:
        """Validate each entry and reject the first backend mismatch.

        Reports zero-based indexes for invalid entry objects and backend mismatches.
        Does not copy, reorder, deduplicate or modify contents. Invoke again after
        edits; a previous successful validation is not a permanent invariant.

        Raises:
            TypeError: Entries is not a list or an item is not a WorkloadEntry.
            ValueError: An entry's backend differs from the first entry's backend.

        Entry/query validation errors propagate unchanged.
        """
        if not isinstance(self.entries, list):
            raise TypeError("entries must be a list")
        backend = None
        for index, entry in enumerate(self.entries):
            if not isinstance(entry, WorkloadEntry):
                raise TypeError(f"entry {index} must be a WorkloadEntry")
            entry.validate()
            if backend is None:
                backend = entry.query.backend
            elif entry.query.backend != backend:
                raise ValueError(
                    f"entry {index} has backend {entry.query.backend!r}; expected {backend!r}"
                )

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[WorkloadEntry]:
        return iter(self.entries)

    @overload
    def __getitem__(self, index: int) -> WorkloadEntry: ...

    @overload
    def __getitem__(self, index: slice) -> list[WorkloadEntry]: ...

    def __getitem__(self, index: int | slice) -> WorkloadEntry | list[WorkloadEntry]:
        """Return an entry reference; slicing returns a shallow list of references."""
        return self.entries[index]
