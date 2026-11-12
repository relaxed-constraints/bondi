"""Selection policies and observations for sustained, closed-loop execution."""

import hashlib
import math
import random
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from itertools import accumulate, cycle
from typing import Literal

from bondi.execution import ExecutionResult


def _seed(seed: int) -> None:
    if type(seed) is not int:
        raise TypeError("seed must be an integer, not a boolean")


def _rng(seed: int, client: int) -> random.Random:
    digest = hashlib.sha256(f"bondi-load-v1:{seed}:{client}".encode("ascii")).digest()
    return random.Random(int.from_bytes(digest, "big"))


@dataclass(frozen=True)
class WeightedRandom:
    """Sample entries with replacement using relative weights and per-client RNGs.

    Args:
        weights: Finite nonnegative weights in workload order, at least one positive.
            Copied to a tuple. The length must match the workload at execution.
        seed: Explicit integer seed. Each call starts fresh client streams.

    Zero-weight entries are never selected. Equal seeds, weights and entry order
    reproduce per-client prefixes, not concurrent interleavings or attempt counts.
    """

    weights: Sequence[float]
    seed: int

    def __post_init__(self) -> None:
        _seed(self.seed)
        weights = tuple(self.weights)
        if not weights or any(
            type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights
        ):
            raise ValueError("weights must be finite nonnegative numbers")
        if not any(weights):
            raise ValueError("at least one weight must be positive")
        object.__setattr__(self, "weights", weights)

    def _stream(self, size: int, client: int) -> Iterator[int]:
        if len(self.weights) != size:
            raise ValueError("weights must match the number of workload entries")
        # Normalize by the maximum first to avoid overflow of the sum.
        maximum = max(self.weights)
        weights = [w / maximum for w in self.weights]
        return _random_stream(_rng(self.seed, client), size, weights)


@dataclass(frozen=True)
class UniformRandom:
    """Select entries with equal probability, using WeightedRandom's stream algorithm.

    Args:
        seed: Explicit integer seed, independently derived for each client.
    """

    seed: int

    def __post_init__(self) -> None:
        _seed(self.seed)

    def _stream(self, size: int, client: int) -> Iterator[int]:
        return WeightedRandom([1] * size, self.seed)._stream(size, client)


@dataclass(frozen=True)
class Sequential:
    """Loop through entries in order, starting each client's cursor at zero.

    Cursors are independent and fresh for each call; they do not reset between
    warm-up and measurement. Clients can initially contend on the same query.
    """

    def _stream(self, size: int, client: int) -> Iterator[int]:
        return cycle(range(size))


def _random_stream(rng, size, weights):
    cumulative = tuple(accumulate(weights))

    def draw():
        while True:
            yield rng.choices(range(size), cum_weights=cumulative, k=1)[0]

    return draw()


Selection = WeightedRandom | UniformRandom | Sequential


@dataclass
class LoadResult:
    """Terminal observation of one admitted invocation; treat callbacks as read-only.

    Args:
        attempt_id: Unique zero-based admission number within this call.
        client_id: Zero-based client index, independent of the workload size.
        client_sequence: Zero-based invocation number within this client.
        workload_position: Selected entry's zero-based workload position.
        phase_started: Phase at admission, before any health preflight.
        admitted_seconds: Admission offset from the shared monotonic origin.
        ended_seconds: Terminal-observation offset, excluding callback delivery.
            On drain expiry this is the expiry observation, not server completion.
        query_started: Whether preflight permitted entry into query execution;
            this is not proof the server received the request.
        result: Completed execution outcome, or None for an unresolved invocation
            at drain expiry. Partial database documents are not retained on failure.
        stop_reason: Why this invocation stopped admissions or remained unresolved.
            Only the triggering failure carries an early-stop reason; other
            in-flight completions can arrive later. Normal outcomes use None.
    """

    attempt_id: int
    client_id: int
    client_sequence: int
    workload_position: int
    phase_started: Literal["warmup", "measurement"]
    admitted_seconds: float
    ended_seconds: float
    query_started: bool
    result: ExecutionResult | None
    stop_reason: Literal["query_error", "database_unavailable", "drain_timeout"] | None = None

    @property
    def duration(self) -> float:
        """Seconds from admission to terminal observation, including preflight.

        This differs from ExecutionResult.elapsed_ms, which excludes preflight.
        """
        return self.ended_seconds - self.admitted_seconds


LoadCallback = Callable[[LoadResult], None | Awaitable[None]]
"""Function type accepted by async executors: receives a LoadResult and returns
None or an awaitable of None. Async executors await asynchronous callbacks.
This is a type alias, not a class to instantiate.
"""

SyncLoadCallback = Callable[[LoadResult], None]
"""Function type accepted by synchronous executors: receives a LoadResult and
returns None. Callbacks run on the calling thread and must not return awaitables.
This is a type alias, not a class to instantiate.
"""
