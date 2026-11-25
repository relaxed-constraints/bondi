"""Native PostgreSQL index definitions and synchronous lifecycle operations."""

import hashlib
from dataclasses import dataclass
from typing import ClassVar, Self

from bondi.connection import PostgresConnection
from bondi.indexes import FieldIndex, IndexSet, _Definition

from .collection import PostgresCollectionRef


@dataclass
class PostgresIndex(_Definition):
    """A native B-tree or JSONB GIN index. SQL expressions and predicates must be trusted.

    Use btree() for ordered expressions and gin() for a JSONB expression.
    The database checks expression syntax and indexability at creation time.
    """

    keys: tuple[tuple[str, int], ...] = ()
    name: str | None = None
    method: str = "btree"
    expression: str | None = None
    operator_class: str | None = None
    condition: str | None = None
    kind: ClassVar[str] = "postgresql"
    _options: ClassVar[tuple] = ("method", "expression", "operator_class", "condition")

    def __post_init__(self):
        self.validate()

    @classmethod
    def btree(
        cls,
        keys: tuple[tuple[str, int], ...],
        *,
        name: str | None = None,
        condition: str | None = None,
    ) -> Self:
        """Describe ordered (SQL expression, direction) keys and an optional partial predicate."""
        return cls(keys=keys, name=name, condition=condition)

    @classmethod
    def gin(
        cls,
        expression: str,
        *,
        operator_class: str = "jsonb_ops",
        name: str | None = None,
        condition: str | None = None,
    ) -> Self:
        """Describe a JSONB GIN expression using jsonb_ops or jsonb_path_ops."""
        return cls(
            method="gin",
            expression=expression,
            operator_class=operator_class,
            name=name,
            condition=condition,
        )

    def validate(self):
        """Validate native options and expression structure without opening a connection."""
        if self.name is not None:
            _identifier(self.name)
        if self.condition is not None:
            _expression(self.condition)
        if self.method == "btree":
            super().validate()
            for key, _ in self.keys:
                _expression(key)
            if self.expression is not None or self.operator_class is not None:
                raise ValueError("B-tree indexes accept ordered keys only")
        elif self.method == "gin":
            _expression(self.expression)
            if self.keys != () or self.operator_class not in ("jsonb_ops", "jsonb_path_ops"):
                raise ValueError("GIN requires one JSONB expression and a supported operator class")
        else:
            raise ValueError("Unsupported PostgreSQL index method")


def _expression(value):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("Expected a nonempty native SQL expression")


def _identifier(value):
    if not isinstance(value, str) or not value or "\0" in value or len(value.encode()) > 63:
        raise ValueError("PostgreSQL identifiers require 1–63 UTF-8 bytes without NUL")


def postgres_index_name(
    collection: PostgresCollectionRef, index: FieldIndex | PostgresIndex
) -> str:
    """Resolve the actual schema-local index name for a target table."""
    if not isinstance(collection, PostgresCollectionRef) or not isinstance(
        index, (FieldIndex, PostgresIndex)
    ):
        raise TypeError("Expected PostgreSQL collection and compatible index")
    base = index.resolved_name
    if index.name is not None:
        _identifier(base)
        return base
    digest = hashlib.sha256((collection.table + "\0" + base).encode()).hexdigest()
    return "bondi_" + digest[:24]


def _targets(indexes, schema):
    if not isinstance(indexes, IndexSet):
        raise TypeError("indexes must be an IndexSet")
    _identifier(schema)
    return {table: PostgresCollectionRef(schema, table) for table in indexes}


def create_postgres_index(
    connection: PostgresConnection,
    *,
    collection: PostgresCollectionRef,
    index: FieldIndex | PostgresIndex,
    timeout: float = 300.0,
) -> str:
    """Build one index synchronously and return its confirmed name."""
    from bondi._index_creation import create_one

    return create_one("postgresql", connection, collection, index, timeout)


def create_postgres_indexes(
    connection: PostgresConnection,
    *,
    indexes: IndexSet,
    schema: str,
    timeout: float = 300.0,
    replace: bool = False,
) -> dict[str, list[str]]:
    """Apply a table-keyed IndexSet in one schema, optionally replacing secondary indexes."""
    from bondi._index_creation import create_many

    return create_many(
        "postgresql", connection, indexes, _targets(indexes, schema), timeout, replace
    )


def remove_postgres_index(
    connection: PostgresConnection,
    *,
    collection: PostgresCollectionRef,
    index: FieldIndex | PostgresIndex,
    timeout: float = 300.0,
) -> bool:
    """Remove the named index from its target table if present."""
    from bondi._index_creation import remove_one

    return remove_one("postgresql", connection, collection, index, timeout)


def remove_postgres_indexes(
    connection: PostgresConnection, *, indexes: IndexSet, schema: str, timeout: float = 300.0
) -> dict[str, list[str]]:
    """Remove named secondary indexes after inspecting all requested tables."""
    from bondi._index_creation import remove_many

    return remove_many("postgresql", connection, indexes, _targets(indexes, schema), timeout)
