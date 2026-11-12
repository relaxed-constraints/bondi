"""Native MongoDB query descriptions."""

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, ClassVar, Self

from bondi.mongodb._conversion import check_filter
from bondi.mongodb._projection import projection_stages
from bondi.mongodb._serialization import (
    _check_canonical_payload,
    _dump_envelope,
    _load_envelope,
)
from bondi.mongodb.aggregate import MongoAggregateQuery
from bondi.mongodb.collection import MongoCollectionRef


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

    def to_aggregate(self) -> MongoAggregateQuery:
        """Convert supported find syntax to an independent aggregation query.

        Stages follow filter, sort, skip, limit, projection order. Empty filters,
        sorts and projections, zero skip and absent limits produce no stage.
        The target is preserved and all mutable pipeline contents are deep-copied.
        Array projections may expand into $set and/or computed $project stages.
        Element matching translations require MongoDB 5.0 or newer.
        No database connection is needed. As with the query constructors, this
        does not validate every MongoDB operator or guarantee server acceptance.

        Returns:
            A new MongoAggregateQuery, leaving this query unchanged.

        Raises:
            TypeError: Current query structure is invalid.
            ValueError: Current values are invalid or conversion is unsupported:
                $where/$near/$nearSphere filters, $natural or duplicate sort keys,
                or unsupported projections. Supports inclusion/exclusion, top-level
                $slice and bounded $elemMatch/positional $ translations; see
                the conversion guide for supported element conditions.

        Examples:
            >>> query = MongoFindQuery(MongoCollectionRef("demo", "items"), {"foo": "bar"},
            ...                        sort=(("baz", 1),), limit=5)
            >>> query.to_aggregate().pipeline
            [{'$match': {'foo': 'bar'}}, {'$sort': {'baz': 1}}, {'$limit': 5}]
        """
        self.validate()
        check_filter(self.filter)
        names = [field for field, _ in self.sort]
        if "$natural" in names or len(set(names)) != len(names):
            raise ValueError("to_aggregate() does not support $natural or duplicate sort keys")

        pipeline: list[dict[str, Any]] = []
        if self.filter:
            pipeline.append({"$match": self.filter})
        if self.sort:
            pipeline.append({"$sort": dict(self.sort)})
        if self.skip:
            pipeline.append({"$skip": self.skip})
        if self.limit is not None:
            pipeline.append({"$limit": self.limit})
        pipeline.extend(projection_stages(self.projection, self.filter))
        return MongoAggregateQuery(self.target, pipeline)

    def to_json(self) -> str:
        """Serialize a version-2 envelope with BSON-aware filter and projection.

        Metadata, sort, skip and limit use ordinary JSON. Filter and projection
        use Canonical Extended JSON, preserving $regex operator documents.
        Native BSON Regex values use $regularExpression. Preserves document order.
        Dates normalize to millisecond precision
        and load as naive UTC datetimes. Binary subtype zero loads as bytes; large
        integers may load as bson.Int64. These preserve the serialized BSON value,
        not necessarily its original Python representation.

        Returns:
            The native query and its metadata in a versioned JSON envelope.

        Raises:
            TypeError: Structural validation or BSON-aware JSON encoding fails.
            ValueError: Validation fails or a document is ambiguous with an Extended
                JSON type wrapper. $regex/$options documents are preserved as operators.
                Unsupported Python values may raise codec exceptions.

        Examples:
            >>> query = MongoFindQuery(MongoCollectionRef("research", "businesses"), {})
            >>> MongoFindQuery.from_json(query.to_json()) == query
            True
        """
        self.validate()
        envelope = {
            "format_version": 2,
            "query_kind": "mongodb.find",
            "target": {"database": self.target.database, "collection": self.target.collection},
            "filter": self.filter,
            "projection": self.projection,
            "sort": self.sort,
            "skip": self.skip,
            "limit": self.limit,
        }
        return _dump_envelope(envelope, ("filter", "projection"))

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Load version-1 or version-2 find envelopes.

        Version-1 projections retain ordinary JSON semantics. New writes use v2,
        changing fingerprints; ambiguous legacy projections cannot be re-saved.
        Whitespace and envelope field order may differ. BSON payloads must use
        Canonical Extended JSON. Unknown, missing and duplicate envelope fields
        are rejected; duplicate document keys are also rejected at any depth.

        Returns:
            The validated [`MongoFindQuery`][bondi.mongodb.MongoFindQuery] restored from the
            envelope.

        Raises:
            TypeError: Input is not a string or a decoded field has an incorrect type.
            ValueError: JSON, the envelope, canonical payload or field values are invalid.
        """
        raw, data = _load_envelope(
            text,
            "mongodb.find",
            {"filter", "projection", "sort", "skip", "limit"},
            ("filter", "projection"),
            versions=(1, 2),
        )
        target = data["target"]
        sort = data["sort"]
        if not isinstance(sort, list) or any(not isinstance(pair, list) for pair in sort):
            raise TypeError("Serialized sort must be an array of arrays")

        query = cls(
            target=MongoCollectionRef(**target),
            filter=data["filter"],
            projection=data["projection"],
            sort=tuple(tuple(pair) for pair in sort),
            skip=data["skip"],
            limit=data["limit"],
        )
        # Validate the old filter independently: a legacy literal projection may
        # intentionally contain wrapper-shaped dictionaries that v2 rejects.
        if raw["format_version"] == 1:
            encoded = _dump_envelope(dict(raw, filter=query.filter), ("filter",))
            _check_canonical_payload(raw, encoded, ("filter",))
        else:
            _check_canonical_payload(raw, query.to_json(), ("filter", "projection"))
        return query

    def fingerprint(self) -> str:
        """Return the SHA-256 hex digest of the current serialized representation.

        Computed on every call after validation. Includes the format version,
        target and all query options; preserves document order. Identifies the
        serialized representation, not semantic equivalence or deployment state.
        Raises the same errors as to_json.

        Returns:
            The hexadecimal SHA-256 digest of the UTF-8 JSON representation.
        """
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
