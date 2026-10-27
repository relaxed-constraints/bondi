"""The structural interface consumed by shared workload code."""

from typing import ClassVar, Protocol


class Query(Protocol):
    """Describe the shared operations of a native query, without inheritance.

    Concrete classes satisfy this protocol by exposing the declared members.
    Type annotations do not enforce runtime behaviour. Workload entries check
    member availability and call validate(); they do not prove method signatures
    or serialization correctness. No runtime-checkable decorator is used.

    Attributes:
        backend: Backend identifier shared by compatible native query types,
            such as mongodb or couchbase. Implementations declare a ClassVar,
            keeping this identifier out of dataclass fields and constructors.

    Loading remains a concrete class responsibility; from_json is not part of
    this instance-level contract. No common filter, pipeline or statement is required.
    """

    backend: ClassVar[str]

    def validate(self) -> None:
        """Check the current query's structural constraints without mutation."""
        ...

    def to_json(self) -> str:
        """Return a validated, versioned native query representation."""
        ...

    def fingerprint(self) -> str:
        """Identify the current serialized representation, not semantic equivalence."""
        ...
