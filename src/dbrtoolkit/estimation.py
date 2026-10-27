"""Small contracts for native-query cardinality estimation."""

from dataclasses import dataclass
from typing import Protocol, TypeVar

QueryT = TypeVar("QueryT", contravariant=True)


@dataclass(frozen=True)
class CardinalityEstimate:
    """Estimated filter cardinality relative to a recorded population.

    Sampling implementations report observed matches and actual sample size.
    Other implementations may leave these diagnostics absent. A zero sample
    match count is not proof that the full population has no matches.
    """

    cardinality: float
    population_size: int
    sample_matches: int | None = None
    sample_size: int | None = None

    @property
    def selectivity(self) -> float:
        """Estimated matching fraction; zero for an empty population."""
        return self.cardinality / self.population_size if self.population_size else 0.0


class CardinalityEstimator(Protocol[QueryT]):
    """Synchronous estimation; concrete implementations define supported queries."""

    def estimate(self, query: QueryT) -> CardinalityEstimate:
        """Estimate cardinality in the implementation's configured population."""
        ...


class AsyncCardinalityEstimator(Protocol[QueryT]):
    """Async estimation for implementations requiring asynchronous I/O."""

    async def estimate(self, query: QueryT) -> CardinalityEstimate:
        """Estimate cardinality in the implementation's configured population."""
        ...
