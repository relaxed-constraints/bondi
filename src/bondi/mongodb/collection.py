"""Logical MongoDB collection identifiers."""

from dataclasses import dataclass


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
