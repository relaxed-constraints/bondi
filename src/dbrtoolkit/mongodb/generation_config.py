"""One configuration for flat-find pattern generation."""

import math
from copy import deepcopy
from dataclasses import dataclass, field


def _positive(name, value, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _fraction(name, value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be finite and between 0 and 1")


def _operators():
    numeric = {"operators": ["lt", "lte", "gt", "gte", "eq"], "weights": [1, 1, 1, 1, 0.5]}
    return {
        "types": {
            "int": numeric,
            "Int64": deepcopy(numeric),
            "float": {"operators": ["lt", "lte", "gt", "gte"], "weights": [1, 1, 1, 1]},
            "str": {
                "operators": ["eq", "ne", "in", "nin", "gte", "lte"],
                "weights": [1, 0.2, 0.4, 0.2, 0.3, 0.3],
            },
            "bool": {"operators": ["eq", "ne"], "weights": [1, 0.3]},
            "datetime": {"operators": ["lt", "lte", "gt", "gte", "eq"], "weights": [1, 1, 1, 1, 1]},
            "ObjectId": {"operators": ["eq", "ne"], "weights": [1, 0.3]},
            "null": {"operators": ["eq", "ne"], "weights": [1, 0.3]},
        },
        "operators": {
            "$exists": {"enabled": True, "chance": 0.3},
            "$type": {"enabled": True, "chance": 0.2},
            "$size": {"enabled": True, "chance": 0.1},
        },
    }


@dataclass
class MongoGenerationConfig:
    """All field, predicate and query-option settings in one place.

    Attributes:
        min_predicates: Minimum distinct filter fields (default 1).
        max_predicates: Maximum distinct filter fields (default 8).
        include_fields: Optional exact normalized Mongo paths; takes precedence over exclusions.
        exclude_fields: Exact paths excluded from filters, sorts and projections. Defaults to _id.
        field_weights: Positive default weight plus ordered glob overrides; last match wins.
        operator_config: Per-type operator/weight lists and conditional special-operator
            enabled/chance settings. See the generation guide for the full structure.
        sort_probability: Fraction of pattern slots requesting sort.
        sort_on_filter_field_ratio: Preference for selecting sort fields from the filter.
        sort_two_field_ratio: Probability of requesting two sort fields instead of one.
        sort_ascending_ratio: Probability of ascending sort direction.
        skip_probability: Fraction of pattern slots requesting skip.
        limit_probability: Fraction of pattern slots requesting limit.
        skip_min: Minimum generated skip (inclusive).
        skip_max: Maximum generated skip (inclusive).
        limit_min: Minimum generated limit (inclusive).
        limit_max: Maximum generated limit (inclusive).
        skip_requires_limit: Force a limit for slots requesting skip.
        projection_probability: Fraction of pattern slots requesting inclusion projection.
        projection_filter_overlap_ratio: Desired fraction of projection fields from the filter.
        projection_min_fields: Minimum requested projection fields.
        projection_max_fields: Maximum requested projection fields.
        projection_exclude_id_ratio: Probability of adding _id: 0, unless _id is projected.

    Probabilities describe proposals, not accepted-workload frequencies. Rejection
    can change the distribution. Values are sampled uniformly from distinct values,
    even with a full-retention Schema. Configs are mutable; generators snapshot
    and validate them at the start of each call. Do not mutate during generation.
    """

    min_predicates: int = 1
    max_predicates: int = 8
    include_fields: list[str] | None = None
    exclude_fields: list[str] = field(default_factory=lambda: ["_id"])
    field_weights: dict = field(default_factory=lambda: {"default": 1.0, "overrides": {}})
    operator_config: dict = field(default_factory=_operators)
    sort_probability: float = 0.3
    sort_on_filter_field_ratio: float = 0.7
    sort_two_field_ratio: float = 0.3
    sort_ascending_ratio: float = 0.8
    skip_probability: float = 0.0
    limit_probability: float = 0.2
    skip_min: int = 0
    skip_max: int = 1000
    limit_min: int = 1
    limit_max: int = 100
    skip_requires_limit: bool = True
    projection_probability: float = 0.0
    projection_filter_overlap_ratio: float = 0.5
    projection_min_fields: int = 1
    projection_max_fields: int = 5
    projection_exclude_id_ratio: float = 0.5

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        """Validate all settings, including nested operator and weight mappings."""
        for low, high, minimum in (
            ("min_predicates", "max_predicates", 1),
            ("skip_min", "skip_max", 0),
            ("limit_min", "limit_max", 1),
            ("projection_min_fields", "projection_max_fields", 1),
        ):
            _positive(low, getattr(self, low), minimum)
            _positive(high, getattr(self, high), minimum)
            if getattr(self, low) > getattr(self, high):
                raise ValueError(f"{low} must not exceed {high}")
        for name in self.__dataclass_fields__:
            if name.endswith(("_probability", "_ratio")):
                _fraction(name, getattr(self, name))
        if type(self.skip_requires_limit) is not bool:
            raise TypeError("skip_requires_limit must be bool")
        for name in ("include_fields", "exclude_fields"):
            value = getattr(self, name)
            if name == "include_fields" and value is None:
                continue
            if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
                raise TypeError(f"{name} must be a list of nonempty paths")
        weights = self.field_weights
        if not isinstance(weights, dict) or set(weights) - {"default", "overrides"}:
            raise ValueError("field_weights accepts default and overrides only")
        overrides = weights.get("overrides", {})
        if not isinstance(overrides, dict) or any(not isinstance(k, str) for k in overrides):
            raise TypeError("field weight overrides must map glob strings to weights")
        for value in (weights.get("default", 1), *overrides.values()):
            _weight(value, positive=True)
        config = self.operator_config
        if not isinstance(config, dict) or set(config) - {"types", "operators"}:
            raise ValueError("operator_config accepts types and operators only")
        types = config.get("types")
        if not isinstance(types, dict) or not types:
            raise ValueError("operator_config.types must be a nonempty mapping")
        for name, settings in types.items():
            if name not in _operators()["types"]:
                raise ValueError(f"Unsupported generation type: {name}")
            if not isinstance(settings, dict) or set(settings) != {"operators", "weights"}:
                raise ValueError("Each type requires operators and weights")
            ops, ws = settings["operators"], settings["weights"]
            if (
                not isinstance(ops, list)
                or not isinstance(ws, list)
                or not ops
                or len(ops) != len(ws)
                or any(not isinstance(op, str) for op in ops)
                or len(set(ops)) != len(ops)
                or set(ops) - {"eq", "ne", "lt", "lte", "gt", "gte", "in", "nin"}
            ):
                raise ValueError("Invalid operator names or mismatched weights")
            for weight in ws:
                _weight(weight)
            if not any(ws):
                raise ValueError("At least one operator weight must be positive per type")
        specials = config.get("operators", {})
        if not isinstance(specials, dict) or set(specials) - {"$exists", "$type", "$size"}:
            raise ValueError("Unsupported special operator")
        for settings in specials.values():
            if not isinstance(settings, dict) or set(settings) - {"enabled", "chance"}:
                raise ValueError("Special operators accept enabled and chance only")
            if type(settings.get("enabled", False)) is not bool:
                raise TypeError("enabled must be bool")
            _fraction("chance", settings.get("chance", 0))


def _weight(value, positive=False):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError("Weights must be finite and nonnegative (field weights strictly positive)")
