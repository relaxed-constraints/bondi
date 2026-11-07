"""Private, conservative translation of find syntax to aggregation syntax."""

from typing import Any


def check_filter(document: dict[str, Any]) -> None:
    """Inspect predicate syntax without interpreting literal or expression data."""
    for name, value in document.items():
        if name in {"$where", "$near", "$nearSphere"}:
            raise ValueError(f"to_aggregate() does not support filter operator {name}")
        if name in {"$and", "$or", "$nor"} and isinstance(value, list):
            for child in value:
                if isinstance(child, dict):
                    check_filter(child)
        elif name == "$elemMatch" and isinstance(value, dict):
            check_filter(value)
        elif not name.startswith("$") and isinstance(value, dict):
            # Only operator documents are syntax; embedded-document equality is data.
            if any(key.startswith("$") for key in value):
                check_filter(value)
        elif name == "$not" and isinstance(value, dict):
            check_filter(value)


def projection_stages(projection: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not projection:
        return []
    normalized = {}
    for field, value in projection.items():
        if (
            not isinstance(field, str)
            or not field
            or any(not part or part.startswith("$") or part.isdigit() for part in field.split("."))
        ):
            raise ValueError(f"to_aggregate() does not support projection path {field!r}")
        if type(value) not in (int, bool):
            raise ValueError(
                f"to_aggregate() supports only inclusion/exclusion projections; field {field!r}"
            )
        normalized[field] = int(bool(value))
    modes = {value for field, value in normalized.items() if field != "_id"}
    if len(modes) > 1:
        raise ValueError("to_aggregate() cannot mix inclusion and exclusion projections")
    return [{"$project": normalized}]
