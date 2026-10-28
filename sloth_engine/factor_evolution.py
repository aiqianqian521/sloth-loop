"""
v2.0 P2: Factor evolution engine — parameter mutation + crossover framework.
Zero new dependencies. Users provide domain-specific operators.
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable


@dataclass
class EvolveConfig:
    """Evolution configuration."""
    population_size: int = 10
    generations: int = 5
    mutation_rate: float = 0.3
    crossover_rate: float = 0.5
    elite_keep: int = 2
    random_seed: int | None = None


@dataclass
class SignalParams:
    """A single signal parameter set (individual in the population)."""
    id: str
    signal_pattern: str = ""
    market_condition: str = ""
    params: dict = field(default_factory=dict)
    fitness: float = 0.0
    generation: int = 0
    parent_ids: list[str] = field(default_factory=list)


class FactorEvolution:
    """Genetic algorithm framework for signal parameter optimization.

    Usage:
        evo = FactorEvolution(config)
        evo.set_mutator(lambda p: {**p, "entry_delay": p["entry_delay"] + random.randint(-1,1)})
        evo.set_crossover(lambda p1, p2: {**p1, "stop_loss": p2["stop_loss"]})
        evo.set_evaluator(lambda params: run_backtest(params)["sharpe"])
        best = evo.evolve(seed_population)  # returns list[SignalParams]
    """

    def __init__(self, config: EvolveConfig | None = None):
        self.config = config or EvolveConfig()
        self._mutator: Callable[[dict], dict] | None = None
        self._crossover: Callable[[dict, dict], dict] | None = None
        self._evaluator: Callable[[dict], float] | None = None
        self._history: list[dict] = []
        if self.config.random_seed is not None:
            random.seed(self.config.random_seed)

    def set_mutator(self, fn: Callable[[dict], dict]) -> None:
        """Set mutation operator: params -> mutated_params."""
        self._mutator = fn

    def set_crossover(self, fn: Callable[[dict, dict], dict]) -> None:
        """Set crossover operator: (params1, params2) -> child_params."""
        self._crossover = fn

    def set_evaluator(self, fn: Callable[[dict], float]) -> None:
        """Set fitness evaluator: params -> fitness_score (higher is better)."""
        self._evaluator = fn

    def evolve(self, seed: list[dict]) -> list[SignalParams]:
        """Run evolution over seed parameter sets.

        Returns sorted list (best first) of all individuals across generations.
        """
        if not self._evaluator:
            raise RuntimeError("Evaluator not set. Call set_evaluator() first.")
        if not seed:
            return []

        population = self._init_population(seed)
        all_individuals: list[SignalParams] = []

        for gen in range(self.config.generations):
            # Evaluate
            for ind in population:
                ind.fitness = self._evaluator(ind.params)

            all_individuals.extend(population)
            population.sort(key=lambda x: x.fitness, reverse=True)

            # Record history
            self._history.append({
                "generation": gen,
                "best_fitness": population[0].fitness,
                "avg_fitness": sum(p.fitness for p in population) / len(population),
                "population_size": len(population),
            })

            if gen == self.config.generations - 1:
                break

            # Elitism
            next_gen = [copy.deepcopy(population[i])
                       for i in range(min(self.config.elite_keep, len(population)))]

            # Fill rest
            while len(next_gen) < self.config.population_size:
                if (self._crossover and random.random() < self.config.crossover_rate
                        and len(population) >= 2):
                    p1, p2 = random.sample(population, 2)
                    child_params = self._crossover(p1.params, p2.params)
                else:
                    parent = random.choice(population)
                    child_params = copy.deepcopy(parent.params)

                if self._mutator and random.random() < self.config.mutation_rate:
                    child_params = self._mutator(child_params)

                child_id = f"EVO-{date.today().strftime('%Y%m%d')}-{len(all_individuals)+1:03d}"
                next_gen.append(SignalParams(
                    id=child_id,
                    signal_pattern=population[0].signal_pattern,
                    params=child_params,
                    generation=gen + 1,
                ))

            population = next_gen

        all_individuals.sort(key=lambda x: x.fitness, reverse=True)
        return all_individuals

    def _init_population(self, seed: list[dict]) -> list[SignalParams]:
        """Initialize population from seed parameter sets."""
        pop = []
        for i, s in enumerate(seed):
            params = s.get("params", s.get("parameters", {}))
            ind = SignalParams(
                id=f"SEED-{i:03d}",
                signal_pattern=s.get("signal_pattern", ""),
                market_condition=s.get("market_condition", ""),
                params=copy.deepcopy(params),
                generation=0,
            )
            pop.append(ind)

        # Pad or trim to population_size
        while len(pop) < self.config.population_size:
            # Duplicate with mutation
            base = random.choice(pop)
            child = copy.deepcopy(base)
            child.id = f"SEED-PAD-{len(pop):03d}"
            if self._mutator:
                child.params = self._mutator(copy.deepcopy(child.params))
            pop.append(child)

        return pop[:self.config.population_size]

    def get_history(self) -> list[dict]:
        """Get per-generation fitness history."""
        return self._history

    def save(self, path: str | Path) -> None:
        """Save evolution history to JSON."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "config": {k: v for k, v in self.config.__dict__.items()
                      if not k.startswith("_")},
            "history": self._history,
            "saved_at": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Built-in operators (domain-agnostic) ──────────────────

def gaussian_mutate(params: dict, keys: list[str] | None = None,
                    sigma: float = 0.1) -> dict:
    """Mutate numeric params with Gaussian noise.
    Only mutates keys present in params with numeric values.
    """
    result = copy.deepcopy(params)
    targets = keys or list(result.keys())
    for k in targets:
        if k in result and isinstance(result[k], (int, float)):
            result[k] += random.gauss(0, max(abs(result[k]) * sigma, sigma))
    return result


def uniform_crossover(p1: dict, p2: dict) -> dict:
    """Uniform crossover: each key randomly from p1 or p2."""
    child = {}
    all_keys = set(p1.keys()) | set(p2.keys())
    for k in all_keys:
        if k in p1 and k in p2:
            child[k] = random.choice([p1[k], p2[k]])
        elif k in p1:
            child[k] = p1[k]
        else:
            child[k] = p2[k]
    return child