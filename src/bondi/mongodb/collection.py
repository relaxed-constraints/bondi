"""Logical MongoDB collection identifiers."""

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class MongoCollectionRef:
    """Identify a MongoDB collection independently of a deployment.

    References compare equal when both names match. They are immutable and
    hashable, so they can be dictionary keys or set members. No connection is
    created and collection existence is not checked.

    Names are preserved exactly, including case and whitespace. Validation
    catches empty names and null characters; it does not implement all MongoDB
    server naming restrictions or guarantee that a server accepts the names.

    Args:
        database: Nonempty database name without null characters.
        collection: Nonempty collection name without null characters.

    Raises:
        TypeError: Either name is not a string.
        ValueError: Either name is empty or contains a null character.

    Examples:
        >>> target = MongoCollectionRef("research", "businesses")
        >>> target.database
        'research'
        >>> target == MongoCollectionRef("research", "businesses")
        True
        >>> len({target, MongoCollectionRef("research", "businesses")})
        1
    """

    database: str
    collection: str

    def __post_init__(self) -> None:
        for field_name in ("database", "collection"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            if "\0" in value:
                raise ValueError(f"{field_name} must not contain null characters")

    @classmethod
    def from_namespace(cls, namespace: str) -> Self:
        """Create a reference from a ``database.collection`` namespace.

        Split at the first dot, preserving any remaining dots in the collection
        name. Case and whitespace are preserved, as with direct construction.

        Args:
            namespace: Database and collection names separated by a dot.

        Returns:
            A collection reference with the parsed names.

        Raises:
            TypeError: The namespace is not a string.
            ValueError: There is no dot, either name is empty, or either name
                contains a null character.

        Examples:
            >>> MongoCollectionRef.from_namespace("research.businesses.archive")
            MongoCollectionRef(database='research', collection='businesses.archive')
        """
        if not isinstance(namespace, str):
            raise TypeError("namespace must be a string")
        database, separator, collection = namespace.partition(".")
        if not separator:
            raise ValueError("namespace must contain a dot separating database and collection")
        return cls(database, collection)
