"""Ordered, single-backend workloads with explicit reference semantics."""

import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self, overload

from bondi.query import Query


def _query_types() -> dict:
    """Resolve native loaders lazily to avoid importing executors during module setup."""
    from bondi.couchbase import CouchbaseQuery
    from bondi.mongodb.aggregate import MongoAggregateQuery
    from bondi.mongodb.query import MongoFindQuery

    return {
        "mongodb.find": MongoFindQuery,
        "mongodb.aggregate": MongoAggregateQuery,
        "couchbase.sqlpp": CouchbaseQuery,
    }


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Nonfinite JSON constant: {value}")


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
    weights or pattern-registry management is provided yet.

    Examples:
        >>> from bondi.mongodb import MongoCollectionRef, MongoFindQuery
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

    def save(self, path: str | os.PathLike[str]) -> None:
        """Atomically replace a UTF-8 JSONL file with this validated workload.

        Each line contains format_version=1, the existing native query envelope
        as a JSON object, and pattern_id. Order, duplicates and pattern IDs are
        preserved; pattern definitions and Python reference sharing are not saved.
        An empty workload writes an empty file. Parent directories must exist.

        Only the three built-in query classes are persistable. A temporary sibling
        file is replaced into place only after every entry serializes successfully.
        On failure, the old destination is preserved and the temporary file removed.
        Do not mutate the workload while saving.

        Raises:
            TypeError: An entry uses an unsupported query implementation.
            ValueError: Workload validation or native serialization fails.
            OSError: File creation, writing or replacement fails.
        """
        self.validate()
        destination = Path(path)
        supported = tuple(_query_types().values())
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                for number, entry in enumerate(self.entries, 1):
                    if type(entry.query) not in supported:
                        raise TypeError(f"entry {number}: unsupported query type for persistence")
                    try:
                        # Standard JSON preserves Extended JSON wrappers as documents.
                        native = json.loads(entry.query.to_json())
                        record = {
                            "format_version": 1,
                            "query": native,
                            "pattern_id": entry.pattern_id,
                        }
                        output.write(
                            json.dumps(
                                record, ensure_ascii=True, allow_nan=False, separators=(",", ":")
                            )
                            + "\n"
                        )
                    except (TypeError, ValueError) as error:
                        raise ValueError(f"entry {number}: {error}") from error
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Self:
        """Load a strict UTF-8 JSONL workload using native query_kind dispatch.

        Each nonempty record must have exactly format_version, query and pattern_id.
        Blank lines, duplicate keys, unsupported kinds/versions and mixed backends
        are rejected with a one-based line number. An empty file is valid. A final
        newline is optional. Loaded entries and queries are independent objects,
        even when duplicate entries originally shared a query reference.

        Raises:
            ValueError: A line has invalid encoding, JSON, metadata or native query data.
            OSError: The file cannot be read.
        """
        loaders = _query_types()
        entries = []
        backend = None
        with Path(path).open("rb") as source:
            for number, line in enumerate(source, 1):
                try:
                    record = json.loads(
                        line.decode("utf-8"),
                        object_pairs_hook=_json_object,
                        parse_constant=_reject_constant,
                    )
                    if not isinstance(record, dict) or set(record) != {
                        "format_version",
                        "query",
                        "pattern_id",
                    }:
                        raise ValueError("Expected exactly format_version, query and pattern_id")
                    if type(record["format_version"]) is not int or record["format_version"] != 1:
                        raise ValueError("Unsupported entry format_version")
                    native = record["query"]
                    if not isinstance(native, dict):
                        raise ValueError("query must be a JSON object")
                    kind = native.get("query_kind")
                    if not isinstance(kind, str) or kind not in loaders:
                        raise ValueError(f"Unsupported query_kind: {kind!r}")
                    query = loaders[kind].from_json(json.dumps(native, allow_nan=False))
                    entry = WorkloadEntry(query, pattern_id=record["pattern_id"])
                    if backend is not None and query.backend != backend:
                        raise ValueError(f"Backend {query.backend!r} differs from {backend!r}")
                    backend = query.backend
                    entries.append(entry)
                except (TypeError, ValueError, KeyError, OverflowError) as error:
                    raise ValueError(f"Line {number}: {error}") from error
        return cls(entries)

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
