"""Persist native PostgreSQL SQL and positional scalar bindings."""

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import ClassVar, Self

from bondi.workload import _json_object, _reject_constant


@dataclass
class PostgresQuery:
    """Describe a read query with optional Psycopg %s positional placeholders.

    The statement is preserved verbatim. SQL grammar and server validation
    run at execution time. Bindings accept strings, finite numbers, booleans and null.
    """

    statement: str
    positional_parameters: list = field(default_factory=list)
    backend: ClassVar[str] = "postgresql"

    def __post_init__(self):
        self.validate()
        self.positional_parameters = self.positional_parameters.copy()

    def validate(self):
        """Validate the envelope and scalar types."""
        if not isinstance(self.statement, str):
            raise TypeError("statement must be a string")
        if not self.statement.strip():
            raise ValueError("statement must not be blank")
        if type(self.positional_parameters) is not list:
            raise TypeError("positional_parameters must be a list")
        for value in self.positional_parameters:
            if value is not None and type(value) not in (str, bool, int, float):
                raise TypeError("Expected positional JSON scalars")
            if type(value) is float and not math.isfinite(value):
                raise ValueError("Nonfinite positional parameter")

    def to_json(self) -> str:
        """Serialize the validated versioned query envelope."""
        self.validate()
        return json.dumps(
            dict(
                format_version=1,
                query_kind="postgresql.sql",
                statement=self.statement,
                positional_parameters=self.positional_parameters,
            ),
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Restore a query from its strict version-1 envelope."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        data = json.loads(text, object_pairs_hook=_json_object, parse_constant=_reject_constant)
        if not isinstance(data, dict) or set(data) != {
            "format_version",
            "query_kind",
            "statement",
            "positional_parameters",
        }:
            raise ValueError("Invalid postgresql.sql envelope")
        if (
            type(data["format_version"]) is not int
            or data["format_version"] != 1
            or data["query_kind"] != "postgresql.sql"
        ):
            raise ValueError("Unsupported PostgreSQL query kind or version")
        return cls(data["statement"], data["positional_parameters"])

    def fingerprint(self) -> str:
        """Hash the exact serialized query and bindings."""
        return hashlib.sha256(self.to_json().encode()).hexdigest()
