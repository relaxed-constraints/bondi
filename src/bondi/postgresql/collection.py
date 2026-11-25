"""PostgreSQL document collections."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresCollectionRef:
    """Identify a document table in the connected database.

    Args:
        schema: PostgreSQL schema name.
        table: PostgreSQL table name.
    """

    schema: str
    table: str

    def __post_init__(self):
        for value in (self.schema, self.table):
            if not isinstance(value, str):
                raise TypeError("schema and table must be strings")
            if not value or "\0" in value or len(value.encode()) > 63:
                raise ValueError("Expected a nonempty identifier of at most 63 bytes without NUL")
