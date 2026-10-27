"""Collection-based MongoDB aggregation descriptions."""

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
class MongoAggregateQuery:
    """Describe a collection-based aggregation without executing it.

    Mutable and unhashable. The pipeline is deep-copied at construction. Later
    assignments and nested edits are neither copied nor automatically validated.
    Validation runs at construction, explicitly, and before serialization or
    fingerprinting. Only top-level stage structure is checked; stage semantics
    and nested pipelines are left to MongoDB. Write stages such as $out and $merge
    are representable: this class does not promise read-only execution.

    Args:
        target: Starting collection, independent of a deployment. References to
            additional collections remain in the native pipeline.
        pipeline: Required ordered list of single-key stage dictionaries. An empty
            list is allowed. Each key must start with $ and contain a name after it.
            Values may be scalars, documents or arrays; their semantics are not checked.

    Raises:
        TypeError: Target, pipeline, a stage or a stage key has an incorrect type.
        ValueError: A stage has other than one key or an invalid stage-name prefix.

    Examples:
        >>> stages = [{"$match": {"stars": {"$gte": 4}}}, {"$limit": 10}]
        >>> query = MongoAggregateQuery(MongoCollectionRef("research", "businesses"), stages)
        >>> query.pipeline[1]["$limit"] = 5
        >>> stages[1]["$limit"]
        10
        >>> restored = MongoAggregateQuery.from_json(query.to_json())
        >>> restored.fingerprint() == query.fingerprint()
        True
    """

    backend: ClassVar[str] = "mongodb"

    target: MongoCollectionRef
    pipeline: list[dict[str, Any]]

    def __post_init__(self) -> None:
        self.validate()
        self.pipeline = deepcopy(self.pipeline)

    def validate(self) -> None:
        """Check current target and top-level stage structure without mutation.

        Raises:
            TypeError: Target, pipeline, stage or stage key has an incorrect type.
            ValueError: A stage does not have exactly one $-prefixed nonempty name.

        Does not validate stage arguments, supported operators, nested pipelines,
        BSON encodability or whether a pipeline writes data.
        """
        if not isinstance(self.target, MongoCollectionRef):
            raise TypeError("target must be a MongoCollectionRef")
        if not isinstance(self.pipeline, list):
            raise TypeError("pipeline must be a list")
        for position, stage in enumerate(self.pipeline):
            if not isinstance(stage, dict):
                raise TypeError(f"pipeline stage {position} must be a dictionary")
            if len(stage) != 1:
                raise ValueError(f"pipeline stage {position} must have exactly one key")
            name = next(iter(stage))
            if not isinstance(name, str):
                raise TypeError(f"pipeline stage {position} key must be a string")
            if not name.startswith("$") or len(name) == 1:
                raise ValueError(
                    f"pipeline stage {position} key must start with $ followed by a name"
                )

    def to_json(self) -> str:
        """Serialize a validated version-1 mongodb.aggregate envelope.

        Uses ordinary JSON metadata and a Canonical Extended JSON pipeline,
        preserving stage and document order. Shares
        find-query BSON normalization: dates load as naive UTC with millisecond
        precision, binary subtype zero as bytes, and large integers may become
        bson.Int64. Literal documents ambiguous with Extended JSON wrappers are
        rejected. Serialization does not modify the query.

        Raises:
            TypeError: Structural validation or BSON-aware encoding fails.
            ValueError: Invalid structure or an ambiguous Extended JSON document.

        Unsupported values may also raise codec exceptions.
        """
        self.validate()
        return _dump_envelope(
            {
                "format_version": 1,
                "query_kind": "mongodb.aggregate",
                "target": {"database": self.target.database, "collection": self.target.collection},
                "pipeline": self.pipeline,
            },
            ("pipeline",),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Load a version-1 aggregation envelope with a canonical BSON pipeline.

        Allows whitespace and envelope-field reordering. Rejects unknown versions,
        wrong query kinds, missing/extra fields and duplicate JSON keys at any depth.

        Raises:
            TypeError: Input or decoded query fields have incorrect types.
            ValueError: Invalid JSON, envelope, pipeline structure or noncanonical payload.
        """
        raw, data = _load_envelope(text, "mongodb.aggregate", {"pipeline"}, ("pipeline",))
        query = cls(MongoCollectionRef(**data["target"]), data["pipeline"])
        _check_canonical_payload(raw, query.to_json(), ("pipeline",))
        return query

    def fingerprint(self) -> str:
        """Compute SHA-256 of the current serialized representation after validation.

        Includes version, kind, target and pipeline; preserves stage and document
        order. Recomputed on every call. Does not identify semantic equivalence or
        deployment state. Raises the same errors as to_json.
        """
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
