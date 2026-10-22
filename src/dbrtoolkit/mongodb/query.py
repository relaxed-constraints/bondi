"""Native MongoDB query descriptions."""

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, ClassVar, Self

from dbrtoolkit.mongodb._serialization import (
    _check_canonical_payload,
    _dump_envelope,
    _load_envelope,
)
from dbrtoolkit.mongodb.collection import MongoCollectionRef


@dataclass
class MongoFindQuery:
    """Describe a MongoDB find operation without executing it.

    This is a mutable, unhashable value object. Filter and projection documents
    are deep-copied on construction, including nested dictionaries and lists.
    Subsequent edits to those input documents do not affect this query, and vice
    versa. Values must support Python's ``deepcopy`` operation.

    Validation runs at construction and before serialization or fingerprinting.
    Later assignments and nested edits are
    ordinary Python mutations: they are neither validated nor defensively copied.
    Validation checks the outer document types and pagination/sort structure;
    it does not validate MongoDB operators, BSON encodability or server acceptance.

    Args:
        target: Logical collection to query, independent of a deployment.
        filter: Required predicate dictionary; use an empty dictionary explicitly
            to describe an unrestricted query.
        projection: Optional projection dictionary. None means no explicit projection.
        sort: Ordered tuple of (field name, direction) tuples. Directions must be
            integer 1 or -1. The empty tuple means no explicit sort. Metadata sorts
            are not supported by this initial interface.
        skip: Nonnegative integer number of results to skip. Booleans are rejected.
        limit: Positive integer result limit, or None for no limit. Zero and booleans
            are rejected; use None explicitly for an unlimited query.

    Raises:
        TypeError: A field has an incorrect type, including a boolean used as an integer.
        ValueError: Pagination bounds or sort names, pair lengths or directions are invalid.

    Examples:
        >>> predicate = {"stars": {"$gte": 4}}
        >>> query = MongoFindQuery(MongoCollectionRef("research", "businesses"), predicate)
        >>> query.filter["stars"]["$gte"] = 5
        >>> predicate["stars"]["$gte"]
        4
        >>> query.limit = 20
        >>> query.limit
        20
    """

    backend: ClassVar[str] = "mongodb"

    target: MongoCollectionRef
    filter: dict[str, Any]
    projection: dict[str, Any] | None = None
    sort: tuple[tuple[str, int], ...] = ()
    skip: int = 0
    limit: int | None = None

    def __post_init__(self) -> None:
        self.validate()
        self.filter = deepcopy(self.filter)
        self.projection = deepcopy(self.projection)

    def validate(self) -> None:
        """Check current structural constraints without modifying the query.

        Raises:
            TypeError: A field has an incorrect type.
            ValueError: A field violates the constructor's value constraints.

        BSON encoding and MongoDB operator validity are not checked here.
        """
        if not isinstance(self.target, MongoCollectionRef):
            raise TypeError("target must be a MongoCollectionRef")
        if not isinstance(self.filter, dict):
            raise TypeError("filter must be a dictionary")
        if self.projection is not None and not isinstance(self.projection, dict):
            raise TypeError("projection must be a dictionary or None")

        if type(self.skip) is not int:
            raise TypeError("skip must be an integer, not a boolean")
        if self.skip < 0:
            raise ValueError("skip must be nonnegative")
        if self.limit is not None:
            if type(self.limit) is not int:
                raise TypeError("limit must be an integer or None, not a boolean")
            if self.limit <= 0:
                raise ValueError("limit must be positive; use None for no limit")

        if not isinstance(self.sort, tuple):
            raise TypeError("sort must be a tuple of (field, direction) tuples")
        for pair in self.sort:
            if not isinstance(pair, tuple):
                raise TypeError("each sort entry must be a tuple")
            if len(pair) != 2:
                raise ValueError("each sort entry must contain a field and direction")
            name, direction = pair
            if not isinstance(name, str):
                raise TypeError("sort field names must be strings")
            if not name or "\0" in name:
                raise ValueError("sort field names must be nonempty without null characters")
            if type(direction) is not int:
                raise TypeError("sort directions must be integers, not booleans")
            if direction not in (1, -1):
                raise ValueError("sort directions must be 1 or -1")

    def to_json(self) -> str:
        """Serialize a validated query as a version-1 Canonical Extended JSON envelope.

        Preserves document and sort order. Dates normalize to millisecond precision
        and load as naive UTC datetimes. Binary subtype zero loads as bytes; large
        integers may load as bson.Int64. These preserve the serialized BSON value,
        not necessarily its original Python representation.

        Raises:
            TypeError: Structural validation or BSON-aware JSON encoding fails.
            ValueError: Validation fails or a document is ambiguous with an Extended
                JSON type wrapper. Use bson.Regex instead of a $regex/$options
                document. Unsupported Python values may raise codec exceptions.

        Examples:
            >>> query = MongoFindQuery(MongoCollectionRef("research", "businesses"), {})
            >>> MongoFindQuery.from_json(query.to_json()) == query
            True
        """
        self.validate()
        envelope = {
            "format_version": 1,
            "query_kind": "mongodb.find",
            "target": {"database": self.target.database, "collection": self.target.collection},
            "filter": self.filter,
            "projection": self.projection,
            "sort": self.sort,
            "skip": self.skip,
            "limit": self.limit,
        }
        return _dump_envelope(envelope)

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Load a version-1 envelope produced by to_json.

        Whitespace and envelope field order may differ. BSON payloads must use
        Canonical Extended JSON. Unknown, missing and duplicate envelope fields
        are rejected; duplicate document keys are also rejected at any depth.

        Raises:
            TypeError: Input is not a string or a decoded field has an incorrect type.
            ValueError: JSON, the envelope, canonical payload or field values are invalid.
        """
        raw, data = _load_envelope(
            text, "mongodb.find", {"filter", "projection", "sort", "skip", "limit"}
        )
        target = data["target"]
        sort = data["sort"]
        if not isinstance(sort, list) or any(not isinstance(pair, list) for pair in sort):
            raise TypeError("Serialized sort must be an array of arrays")

        # Canonical numberLong decodes as Int64. Envelope integers are ordinary
        # Python ints; BSON type distinctions inside filter/projection stay intact.
        def envelope_int(value):
            return int(value) if isinstance(value, int) and not isinstance(value, bool) else value

        query = cls(
            target=MongoCollectionRef(**target),
            filter=data["filter"],
            projection=data["projection"],
            sort=tuple(tuple(envelope_int(v) for v in pair) for pair in sort),
            skip=envelope_int(data["skip"]),
            limit=envelope_int(data["limit"]),
        )
        _check_canonical_payload(raw, query.to_json(), ("filter", "projection"))
        return query

    def fingerprint(self) -> str:
        """Return the SHA-256 hex digest of the current serialized representation.

        Computed on every call after validation. Includes the format version,
        target and all query options; preserves document order. Identifies the
        serialized representation, not semantic equivalence or deployment state.
        Raises the same errors as to_json.
        """
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
