"""Bounded synchronous pattern generation over one observed collection schema."""

import inspect
import math
import random
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Any, Literal, overload

from bson import Int64, json_util

from dbrtoolkit.estimation import CardinalityEstimate, CardinalityEstimator
from dbrtoolkit.mongodb.collection import MongoCollectionRef
from dbrtoolkit.mongodb.generation_config import MongoGenerationConfig, _fraction, _positive
from dbrtoolkit.mongodb.pattern import MongoQueryPattern, _field_path, _value_type
from dbrtoolkit.mongodb.query import MongoFindQuery
from dbrtoolkit.schema import ARRAY_ELEMENT, Schema
from dbrtoolkit.workload import Workload, WorkloadEntry

_BSON_NAMES = {
    "str": "string",
    "int": "int",
    "Int64": "long",
    "float": "double",
    "bool": "bool",
    "datetime": "date",
    "ObjectId": "objectId",
    "null": "null",
    "object": "object",
    "array": "array",
}


def _snapshot(stats):
    return MappingProxyType(
        {k: _snapshot(v) if isinstance(v, dict) else v for k, v in stats.items()}
    )


class WorkloadGenerationError(RuntimeError):
    """Generation exhausted a budget without a complete workload; stats describe progress."""

    def __init__(self, message: str, stats: dict):
        self.stats = _snapshot(stats)
        super().__init__(message)


@dataclass
class _Field:
    name: str
    pools: list = field(default_factory=list)
    bson_types: set = field(default_factory=set)
    missing: bool = False
    array: bool = False


def _choice(rng, items, weights):
    scale = max(weights)
    return rng.choices(items, weights=[w / scale for w in weights], k=1)[0]


def _sample_fields(rng, names, count, config):
    names = sorted(set(names))
    selected = []
    for _ in range(min(count, len(names))):
        weights = []
        for name in names:
            weight = config.field_weights.get("default", 1)
            for glob, value in config.field_weights.get("overrides", {}).items():
                if fnmatchcase(name, glob):
                    weight = value
            weights.append(weight)
        name = _choice(rng, names, weights)
        selected.append(name)
        names.remove(name)
    return selected


def _pool_values(values):
    """Canonical BSON values and ordering, independent of set/hash iteration and counts."""
    by_type = {}
    for value in values:
        kind = _value_type(value)
        if kind == "Int64":
            value = Int64(value)
        encoded = json_util.dumps(value, json_options=json_util.CANONICAL_JSON_OPTIONS)
        # Dates normalize to BSON milliseconds and UTC, matching query persistence.
        value = json_util.loads(encoded)
        by_type.setdefault(kind, {})[encoded] = value
    return [
        (kind, tuple(pool[key] for key in sorted(pool))) for kind, pool in sorted(by_type.items())
    ]


def _fields(schema, config, check):
    if schema.value_mode == "none":
        raise ValueError("Generation requires Schema values='distinct' or values='full'")
    fields = {}
    for display, node in sorted(schema.flat_fields.items()):
        check()
        parts = [p for p in node.path if p is not ARRAY_ELEMENT]
        name = ".".join(parts)
        if config.include_fields is not None:
            if name not in config.include_fields and display not in config.include_fields:
                continue
        elif name in config.exclude_fields or display in config.exclude_fields:
            continue
        if any("." in p or "\0" in p for p in parts):
            raise ValueError(
                f"Cannot generate dot-path queries for {display!r}; exclude this field"
            )
        _field_path(name)
        item = fields.setdefault(name, _Field(name))
        item.missing |= bool(node.has_missing)
        for kind, variant in sorted(node.types.items()):
            item.bson_types.add(_BSON_NAMES.get(kind, kind))
            item.array |= kind == "array"
            values = variant.values
            if values:
                for value_kind, pool in _pool_values(values):
                    check()
                    if value_kind in config.operator_config["types"]:
                        item.pools.append((value_kind, pool))
    return {name: item for name, item in fields.items() if item.pools}


def _special(config, name, rng):
    setting = config.operator_config.get("operators", {}).get("$" + name, {})
    return setting.get("enabled", False) and rng.random() < setting.get("chance", 0)


def _predicate(item, config, rng):
    eligible = []
    for kind, pool in item.pools:
        setting = config.operator_config["types"][kind]
        ops = [
            (op, w)
            for op, w in zip(setting["operators"], setting["weights"])
            if w > 0 and (op != "in" or len(pool) >= 2)
        ]
        if ops:
            eligible.append((kind, pool, ops))
    if not eligible:
        return None
    kind, pool, ops = rng.choice(eligible)
    operator = _choice(rng, [op for op, _ in ops], [w for _, w in ops])
    arity = (
        rng.randint(2 if operator == "in" else 1, min(10, len(pool)))
        if operator in ("in", "nin")
        else 1
    )
    values = rng.sample(pool, arity)
    operand = values if operator in ("in", "nin") else values[0]
    if item.missing and _special(config, "exists", rng):
        operator, operand = "exists", rng.choice([True, False])
    elif len(item.bson_types) > 1 and _special(config, "type", rng):
        operator, operand = "type", rng.choice(sorted(item.bson_types))
    elif item.array and _special(config, "size", rng):
        operator, operand = "size", rng.randint(0, 5)
    expression = operand if operator == "eq" else {"$" + operator: operand}
    return expression, pool


def _conflicts(path, selected):
    return any(path.startswith(p + ".") or p.startswith(path + ".") for p in selected)


def _options(filter_fields, all_fields, config, presence, rng):
    sort = []
    if presence["sort"]:
        count = 2 if rng.random() < config.sort_two_field_ratio else 1
        for _ in range(count):
            used = [name for name, _ in sort]
            preferred = (
                filter_fields if rng.random() < config.sort_on_filter_field_ratio else all_fields
            )
            available = [f for f in preferred if f not in used]
            if not available:
                available = [f for f in all_fields if f not in used]
            if not available:
                break
            name = _sample_fields(rng, available, 1, config)[0]
            sort.append((name, 1 if rng.random() < config.sort_ascending_ratio else -1))
    projection = None
    if presence["projection"]:
        count = rng.randint(config.projection_min_fields, config.projection_max_fields)
        overlap = int(count * config.projection_filter_overlap_ratio)
        selected = []
        for pool, n in ((filter_fields, overlap), (all_fields, count - overlap)):
            for _ in range(n):
                available = [f for f in pool if f not in selected and not _conflicts(f, selected)]
                if not available:
                    break
                selected.extend(_sample_fields(rng, available, 1, config))
        if not selected:
            selected = _sample_fields(rng, all_fields, 1, config)
        projection = dict.fromkeys(selected, 1)
        if not any(f == "_id" or f.startswith("_id.") for f in projection) and (
            rng.random() < config.projection_exclude_id_ratio
        ):
            projection["_id"] = 0
    return dict(
        sort=tuple(sort),
        projection=projection,
        skip=rng.randint(config.skip_min, config.skip_max) if presence["skip"] else 0,
        limit=rng.randint(config.limit_min, config.limit_max) if presence["limit"] else None,
    )


def _instantiate(pattern, pools, rng):
    predicates = {}
    for predicate in pattern.predicates:
        op = predicate.operator
        if op in ("exists", "type"):
            operand = predicate.fixed_value
        elif op == "size":
            operand = rng.randint(0, 5)
        else:
            values = rng.sample(pools[predicate.field], predicate.arity)
            operand = values if op in ("in", "nin") else values[0]
        predicates[predicate.field] = operand if op == "eq" else {"$" + op: operand}
    return MongoFindQuery(
        pattern.target,
        predicates,
        sort=pattern.sort,
        projection=None if pattern.projection is None else dict(pattern.projection),
        skip=pattern.skip,
        limit=pattern.limit,
    )


class MongoWorkloadGenerator:
    """Generate flat-find patterns for one collection, with optional selectivity checks.

    Args:
        target: Collection targeted by every generated query.
        schema: Observed Schema retaining distinct or full values. Frequencies are ignored.
        estimator: Optional prepared synchronous CardinalityEstimator[MongoFindQuery].
            Required only when selectivity bounds are active. Never opened or closed here.
        config: One MongoGenerationConfig; omitted settings use documented defaults.

    No database connection or event loop is created. Schema and config are retained
    by reference and read at each generate() call; do not mutate inputs during a
    call. Calls on one generator must not overlap. Patterns support flat filters
    only; logical expressions, elemMatch and aggregation generation are deferred.
    """

    def __init__(
        self,
        *,
        target: MongoCollectionRef,
        schema: Schema,
        estimator: CardinalityEstimator[MongoFindQuery] | None = None,
        config: MongoGenerationConfig | None = None,
    ):
        if not isinstance(target, MongoCollectionRef) or not isinstance(schema, Schema):
            raise TypeError("Expected MongoCollectionRef target and Schema schema")
        if config is not None and not isinstance(config, MongoGenerationConfig):
            raise TypeError("config must be MongoGenerationConfig")
        if estimator is not None and (
            not callable(getattr(estimator, "estimate", None))
            or inspect.iscoroutinefunction(estimator.estimate)
        ):
            raise TypeError("estimator must expose a synchronous estimate(query) method")
        if schema.value_mode == "none":
            raise ValueError("Generation requires Schema values='distinct' or values='full'")
        self.target, self.schema, self.estimator = target, schema, estimator
        self.config = config if config is not None else MongoGenerationConfig()
        self.config.validate()
        self._last_stats = {}

    @property
    def last_stats(self) -> Mapping[str, Any]:
        """Read-only snapshot of the latest generation call, including interrupted/failed calls."""
        return _snapshot(self._last_stats)

    @overload
    def generate(
        self,
        *,
        num_patterns: int,
        instances_per_pattern: int = 1,
        return_patterns: Literal[False] = False,
        seed: int | None = None,
        min_selectivity: float = 0.0,
        max_selectivity: float = 1.0,
        validate_pattern: Callable | None = None,
        max_candidate_attempts: int = 10_000,
        max_instance_attempts: int = 1000,
        timeout_seconds: float = 60,
    ) -> Workload: ...

    @overload
    def generate(
        self,
        *,
        num_patterns: int,
        instances_per_pattern: int = 1,
        return_patterns: Literal[True],
        seed: int | None = None,
        min_selectivity: float = 0.0,
        max_selectivity: float = 1.0,
        validate_pattern: Callable | None = None,
        max_candidate_attempts: int = 10_000,
        max_instance_attempts: int = 1000,
        timeout_seconds: float = 60,
    ) -> tuple[Workload, list[MongoQueryPattern]]: ...

    def generate(
        self,
        *,
        num_patterns: int,
        instances_per_pattern: int = 1,
        return_patterns: bool = False,
        seed: int | None = None,
        min_selectivity: float = 0.0,
        max_selectivity: float = 1.0,
        validate_pattern: Callable | None = None,
        max_candidate_attempts: int = 10_000,
        max_instance_attempts: int = 1000,
        timeout_seconds: float = 60,
    ) -> Workload | tuple[Workload, list[MongoQueryPattern]]:
        """Return exactly N patterns of K instances, or raise WorkloadGenerationError.

        Args:
            num_patterns: Positive number of distinct complete patterns.
            instances_per_pattern: Positive group size; one gives unique-pattern queries.
            return_patterns: Also return a list indexed by each entry's pattern_id.
            seed: Local RNG seed. Reproducibility requires fixed inputs and estimator responses.
            min_selectivity: Inclusive lower estimated matching fraction, before skip/limit.
            max_selectivity: Inclusive upper bound; [0, 1] disables estimation.
            validate_pattern: Callback(candidate, tuple_of_completed_patterns) -> bool,
                before estimation. Exceptions propagate unchanged.
            max_candidate_attempts: Global budget for discovering patterns.
            max_instance_attempts: Attempts per additional instance, not per workload.
            timeout_seconds: Monotonic deadline, checked between operations including
                estimator/callback calls. Does not interrupt a running external call.

        Each group fixes fields/operators/types/membership arity and exact options;
        exists/type literals are fixed. Duplicate full instances are allowed.
        Output is shuffled. No partial workload is returned; errors expose stats.
        Estimator errors propagate. The estimator owns its operation timeout.
        """
        self._last_stats = {}
        for name, value in [
            ("num_patterns", num_patterns),
            ("instances_per_pattern", instances_per_pattern),
            ("max_candidate_attempts", max_candidate_attempts),
            ("max_instance_attempts", max_instance_attempts),
        ]:
            _positive(name, value)
        if type(return_patterns) is not bool:
            raise TypeError("return_patterns must be bool")
        if seed is not None and type(seed) is not int:
            raise TypeError("seed must be int or None")
        _fraction("min_selectivity", min_selectivity)
        _fraction("max_selectivity", max_selectivity)
        if min_selectivity > max_selectivity:
            raise ValueError("min_selectivity must not exceed max_selectivity")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite")
        if validate_pattern is not None and (
            not callable(validate_pattern) or inspect.iscoroutinefunction(validate_pattern)
        ):
            raise TypeError("validate_pattern must be a synchronous callable")
        constrained = min_selectivity > 0 or max_selectivity < 1
        if constrained and self.estimator is None:
            raise ValueError("Selectivity constraints require a prepared estimator")
        config = deepcopy(self.config)
        config.validate()
        rng, started = random.Random(seed), time.monotonic()
        stats = dict(
            candidate_attempts=0,
            value_attempts=0,
            duplicate_candidates=0,
            structural_rejections=0,
            validation_rejections=0,
            selectivity_rejections=0,
            discarded_groups=0,
            estimator_calls=0,
            completed_patterns=0,
            elapsed_seconds=0.0,
        )

        def check():
            stats["elapsed_seconds"] = time.monotonic() - started
            if stats["elapsed_seconds"] >= timeout_seconds:
                raise WorkloadGenerationError("Generation deadline exceeded", stats)

        def accepted(query):
            check()
            if not constrained:
                return True
            stats["estimator_calls"] += 1
            # Isolate user-supplied estimators from the candidate retained for output.
            result = self.estimator.estimate(deepcopy(query))
            if inspect.iscoroutine(result):
                result.close()
                raise TypeError("Use a synchronous estimator")
            if not isinstance(result, CardinalityEstimate):
                raise TypeError("estimate() must return CardinalityEstimate")
            if (
                type(result.population_size) is not int
                or result.population_size < 0
                or type(result.cardinality) not in (int, float)
                or not math.isfinite(result.cardinality)
                or not 0 <= result.cardinality <= result.population_size
            ):
                raise ValueError("Estimator returned invalid cardinality/population")
            check()
            ok = min_selectivity <= result.selectivity <= max_selectivity
            if not ok:
                stats["selectivity_rejections"] += 1
            return ok

        try:
            fields = _fields(self.schema, config, check)
            if len(fields) < config.min_predicates:
                raise WorkloadGenerationError("Insufficient eligible fields", stats)
            patterns, entries, seen = [], [], set()
            slot = None
            while (
                len(patterns) < num_patterns
                and stats["candidate_attempts"] < max_candidate_attempts
            ):
                check()
                if slot is None:
                    count = rng.randint(
                        config.min_predicates, min(config.max_predicates, len(fields))
                    )
                    presence = {
                        name: rng.random() < getattr(config, name + "_probability")
                        for name in ("sort", "skip", "limit", "projection")
                    }
                    if presence["skip"] and config.skip_requires_limit:
                        presence["limit"] = True
                    slot = count, presence
                    stats["pending_pattern_target"] = dict(
                        pattern_id=len(patterns), num_predicates=count, **presence
                    )
                count, presence = slot
                stats["candidate_attempts"] += 1
                names = _sample_fields(rng, fields, count, config)
                predicates, pools = {}, {}
                for name in names:
                    predicate = _predicate(fields[name], config, rng)
                    if predicate is not None:
                        predicates[name], pools[name] = predicate
                if len(predicates) != count:
                    stats["structural_rejections"] += 1
                    continue
                query = MongoFindQuery(
                    self.target, predicates, **_options(names, list(fields), config, presence, rng)
                )
                pattern = MongoQueryPattern.from_query(query)
                if pattern in seen:
                    stats["duplicate_candidates"] += 1
                    continue
                if validate_pattern is not None:
                    valid = validate_pattern(pattern, tuple(patterns))
                    if inspect.iscoroutine(valid):
                        valid.close()
                    if type(valid) is not bool:
                        raise TypeError("validate_pattern must return bool")
                    check()
                    if not valid:
                        stats["validation_rejections"] += 1
                        continue
                if not accepted(query):
                    continue
                group = [query]
                while len(group) < instances_per_pattern:
                    for _ in range(max_instance_attempts):
                        check()
                        stats["value_attempts"] += 1
                        query = _instantiate(pattern, pools, rng)
                        if accepted(query):
                            group.append(query)
                            break
                    else:
                        break
                if len(group) != instances_per_pattern:
                    stats["discarded_groups"] += 1
                    continue
                entries.extend(WorkloadEntry(q, len(patterns)) for q in group)
                patterns.append(pattern)
                seen.add(pattern)
                stats["completed_patterns"] = len(patterns)
                stats.pop("pending_pattern_target", None)
                slot = None
            check()
            if len(patterns) != num_patterns:
                raise WorkloadGenerationError("Candidate attempt budget exhausted", stats)
            rng.shuffle(entries)
            workload = Workload(entries)
            check()
            return (workload, patterns) if return_patterns else workload
        finally:
            stats["elapsed_seconds"] = time.monotonic() - started
            self._last_stats = deepcopy(stats)
