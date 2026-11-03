"""Query-aware JSON input decoding without database access."""

import json
import math
from typing import Any

from bson.errors import BSONError

from bondi.mongodb._serialization import _decode_bson


def loads_query_json(text: str) -> Any:
    """Decode JSON/BSON values while preserving MongoDB regex operators.

    Accepts canonical and relaxed Extended JSON supported by PyMongo. Objects
    containing $regex remain dictionaries rather than legacy BSON regex wrappers;
    explicit $regularExpression wrappers decode as bson.Regex. The same decoding
    rules are used by BONDI query persistence. Dates load as naive UTC datetimes.

    This decodes data only: it does not validate query operators, construct query
    objects, repair responses, or execute queries. Object order is preserved.
    Wrapper-shaped literal documents cannot be distinguished from BSON values,
    even inside $literal; explicit type wrappers are interpreted as BSON.

    Args:
        text: JSON string, including a top-level object, array or scalar.

    Returns:
        Decoded Python data, including BSON types where explicitly represented.

    Raises:
        TypeError: text is not a string.
        ValueError: Invalid JSON, duplicate keys, bare NaN/Infinity, numeric
            overflow, malformed BSON wrappers or excessive nesting.

    Examples:
        >>> loads_query_json('{"tags":{"$elemMatch":{"$regex":"^python$"}}}')
        {'tags': {'$elemMatch': {'$regex': '^python$'}}}
        >>> loads_query_json('{"_id":{"$oid":"0123456789abcdef01234567"}}')
        {'_id': ObjectId('0123456789abcdef01234567')}
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"Nonstandard JSON numeric literal: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"JSON number outside finite float range: {value}")
        return number

    try:
        raw = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
        return _decode_bson(raw)
    except (ValueError, TypeError, KeyError, BSONError, OverflowError, RecursionError) as error:
        raise ValueError(f"Invalid query JSON: {error}") from error
