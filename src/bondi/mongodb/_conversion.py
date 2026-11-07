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
