"""Genetic algorithm engine — evolve solutions through selection, crossover, mutation.

DNA: Evolver (iterative optimisation) + DEAP (evolutionary computation patterns).

Pure Python implementation using only stdlib ``random``.  No external dependencies.
Supports tournament selection, single-point crossover, Gaussian mutation, and
full generational evolution with fitness-history tracking.

Usage::

    evolver = Evolver(seed=42)

    def fitness_fn(individual: list[float]) -> float:
        return -sum((x - 3.14) ** 2 for x in individual)  # maximise closeness to 3.14

    best, history = evolver.evolve(
        population_size=100,
        fitness_fn=fitness_fn,
        generations=50,
        mutation_rate=0.1,
        crossover_rate=0.7,
    )
"""

from __future__ import annotations

import copy
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, TypeVar

T = TypeVar("T", bound=Sequence)


@dataclass
class EvolveResult:
    """Result of an evolution run."""
    best_individual: list[float]
    best_fitness: float
    fitness_history: list[float]          # best fitness per generation
    avg_fitness_history: list[float]      # average fitness per generation
    generations_run: int
    converged: bool = False
    convergence_generation: int = -1


class Evolver:
    """Genetic algorithm engine with tournament selection, crossover, and mutation.

    All genetic operators are pure-Python and require no external libraries.
    The engine operates on ``list[float]`` individuals (real-valued vectors).

    Parameters:
        seed: Optional RNG seed for reproducibility.
        elite_count: Number of top individuals preserved each generation (elitism).
        convergence_threshold: Stop if best fitness changes less than this for
            ``convergence_patience`` generations.
        convergence_patience: Generations without improvement before early stop.
    """

    def __init__(
        self,
        seed: Optional[int] = None,
        elite_count: int = 2,
        convergence_threshold: float = 1e-6,
        convergence_patience: int = 20,
    ):
        self._rng = random.Random(seed)
        self.elite_count = max(0, elite_count)
        self.convergence_threshold = convergence_threshold
        self.convergence_patience = convergence_patience

    # ── Public API ────────────────────────────────────────────────────

    def evolve(
        self,
        population_size: int,
        fitness_fn: Callable[[list[float]], float],
        generations: int,
        mutation_rate: float = 0.1,
        crossover_rate: float = 0.7,
        genome_size: int = 10,
        init_range: tuple[float, float] = (-10.0, 10.0),
    ) -> EvolveResult:
        """Run a full genetic algorithm evolution.

        Args:
            population_size: Number of individuals per generation.
            fitness_fn: Function that scores an individual (higher = better).
            generations: Maximum number of generations to evolve.
            mutation_rate: Probability each gene mutates (0.0–1.0).
            crossover_rate: Probability a pair of parents produce offspring via crossover.
            genome_size: Number of genes per individual.
            init_range: (min, max) range for initial gene values.

        Returns:
            EvolveResult with best individual and full fitness history.
        """
        # Initialise population
        population = self._init_population(population_size, genome_size, init_range)
        fitness_history: list[float] = []
        avg_history: list[float] = []
        best_ever: Optional[list[float]] = None
        best_fitness_ever = float("-inf")
        no_improve = 0
        converged = False
        conv_gen = -1

        for gen in range(generations):
            # Evaluate
            scored = [(ind, fitness_fn(ind)) for ind in population]
            scored.sort(key=lambda x: x[1], reverse=True)  # best first

            best_fitness = scored[0][1]
            best_individual = scored[0][0]
            avg_fitness = statistics.mean(f for _, f in scored)
            fitness_history.append(best_fitness)
            avg_history.append(avg_fitness)

            # Track best ever
            if best_fitness > best_fitness_ever + self.convergence_threshold:
                best_fitness_ever = best_fitness
                best_ever = copy.deepcopy(best_individual)
                no_improve = 0
            else:
                no_improve += 1
                if no_improve >= self.convergence_patience:
                    converged = True
                    conv_gen = gen
                    break

            # Build next generation
            next_pop: list[list[float]] = []

            # Elitism: preserve top individuals
            for i in range(min(self.elite_count, len(scored))):
                next_pop.append(copy.deepcopy(scored[i][0]))

            # Fill rest with offspring
            while len(next_pop) < population_size:
                parent1 = self.tournament_select(scored, tournament_size=3)
                parent2 = self.tournament_select(scored, tournament_size=3)

                if self._rng.random() < crossover_rate:
                    child1, child2 = self.crossover(parent1, parent2)
                else:
                    child1, child2 = copy.deepcopy(parent1), copy.deepcopy(parent2)

                child1 = self.mutate(child1, mutation_rate, init_range)
                child2 = self.mutate(child2, mutation_rate, init_range)

                next_pop.append(child1)
                if len(next_pop) < population_size:
                    next_pop.append(child2)

            population = next_pop

        # Final evaluation
        if best_ever is None:
            scored = [(ind, fitness_fn(ind)) for ind in population]
            scored.sort(key=lambda x: x[1], reverse=True)
            best_ever = scored[0][0]
            best_fitness_ever = scored[0][1]

        return EvolveResult(
            best_individual=best_ever,
            best_fitness=best_fitness_ever,
            fitness_history=fitness_history,
            avg_fitness_history=avg_history,
            generations_run=len(fitness_history),
            converged=converged,
            convergence_generation=conv_gen,
        )

    def tournament_select(
        self,
        scored_population: list[tuple[list[float], float]],
        tournament_size: int = 3,
    ) -> list[float]:
        """Select an individual using tournament selection.

        Randomly picks *tournament_size* candidates and returns the fittest.

        Args:
            scored_population: List of (individual, fitness) pairs sorted best-first.
            tournament_size: Number of candidates in the tournament.

        Returns:
            The winning individual (a copy).
        """
        candidates = self._rng.sample(
            scored_population, min(tournament_size, len(scored_population))
        )
        winner = max(candidates, key=lambda x: x[1])
        return copy.deepcopy(winner[0])

    def crossover(
        self,
        parent1: list[float],
        parent2: list[float],
    ) -> tuple[list[float], list[float]]:
        """Single-point crossover between two parents.

        Picks a random crossover point and swaps gene segments beyond it.

        Args:
            parent1: First parent genome.
            parent2: Second parent genome.

        Returns:
            Tuple of (child1, child2).
        """
        if len(parent1) < 2:
            return copy.deepcopy(parent1), copy.deepcopy(parent2)

        point = self._rng.randint(1, len(parent1) - 1)
        child1 = parent1[:point] + parent2[point:]
        child2 = parent2[:point] + parent1[point:]
        return child1, child2

    def mutate(
        self,
        individual: list[float],
        mutation_rate: float,
        value_range: tuple[float, float] = (-10.0, 10.0),
    ) -> list[float]:
        """Apply Gaussian mutation to each gene independently.

        Each gene has a *mutation_rate* probability of being perturbed
        by a random amount drawn from N(0, sigma) where sigma is 10%
        of the value range width.

        Args:
            individual: The genome to mutate.
            mutation_rate: Probability each gene mutates (0.0–1.0).
            value_range: (min, max) — used to determine mutation sigma
                and to clamp mutated values.

        Returns:
            The mutated individual (same object, mutated in place).
        """
        range_width = value_range[1] - value_range[0]
        sigma = range_width * 0.1

        for i in range(len(individual)):
            if self._rng.random() < mutation_rate:
                individual[i] += self._rng.gauss(0.0, sigma)
                # Clamp to range
                individual[i] = max(value_range[0], min(value_range[1], individual[i]))

        return individual

    # ── Internals ─────────────────────────────────────────────────────

    def _init_population(
        self,
        size: int,
        genome_size: int,
        value_range: tuple[float, float],
    ) -> list[list[float]]:
        """Generate a random initial population."""
        lo, hi = value_range
        return [
            [self._rng.uniform(lo, hi) for _ in range(genome_size)]
            for _ in range(size)
        ]


# ── Self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("EVOLVER SELF-TEST")
    print("=" * 60)

    evolver = Evolver(seed=42, convergence_patience=30)

    # ── Test 1: Simple function optimisation ──────────────────────────
    print("\n── Test 1: Optimise to target vector ──")
    TARGET = [3.0, -1.5, 7.0, 0.0, 2.5]

    def fitness_to_target(ind: list[float]) -> float:
        """Maximise: negative MSE to target."""
        mse = sum((a - b) ** 2 for a, b in zip(ind, TARGET))
        return -mse

    result = evolver.evolve(
        population_size=80,
        fitness_fn=fitness_to_target,
        generations=200,
        mutation_rate=0.15,
        crossover_rate=0.6,
        genome_size=5,
        init_range=(-10.0, 10.0),
    )

    print(f"Generations run: {result.generations_run}")
    print(f"Converged: {result.converged}")
    print(f"Best fitness: {result.best_fitness:.4f}")
    print(f"Best individual: {[round(x, 3) for x in result.best_individual]}")
    print(f"Target:          {TARGET}")
    print(f"First gen best:  {result.fitness_history[0]:.4f}")
    print(f"Final gen best:  {result.fitness_history[-1]:.4f}")

    # Should be close to target
    for a, b in zip(result.best_individual, TARGET):
        assert abs(a - b) < 2.0, f"Gene {a} far from target {b}"
    assert result.best_fitness > -20.0, "Fitness should be improving"

    # ── Test 2: Binary string (all-ones) ──────────────────────────────
    print("\n── Test 2: Evolve all-ones vector ──")

    def fitness_ones(ind: list[float]) -> float:
        """Maximise: sum of genes (encourages high values)."""
        return sum(ind)

    result2 = evolver.evolve(
        population_size=50,
        fitness_fn=fitness_ones,
        generations=100,
        mutation_rate=0.2,
        crossover_rate=0.5,
        genome_size=8,
        init_range=(0.0, 10.0),
    )

    print(f"Generations: {result2.generations_run}")
    print(f"Best fitness: {result2.best_fitness:.2f}")
    print(f"Best individual: {[round(x, 2) for x in result2.best_individual]}")
    assert result2.best_fitness > 50.0, "Should find high-sum individual"

    # ── Test 3: Tournament select ─────────────────────────────────────
    print("\n── Test 3: Tournament selection ──")
    scored = [
        ([1.0, 2.0], 10.0),
        ([3.0, 4.0], 5.0),
        ([5.0, 6.0], 1.0),
        ([7.0, 8.0], 100.0),
    ]
    # Run many tournaments; best should win most often
    wins = {0: 0, 1: 0, 2: 0, 3: 0}
    for _ in range(1000):
        winner = evolver.tournament_select(scored, tournament_size=3)
        # Identify winner by value
        if winner == [1.0, 2.0]:
            wins[0] += 1
        elif winner == [3.0, 4.0]:
            wins[1] += 1
        elif winner == [5.0, 6.0]:
            wins[2] += 1
        elif winner == [7.0, 8.0]:
            wins[3] += 1

    print(f"Win distribution (idx3 should dominate): {wins}")
    assert wins[3] > wins[0], "Best individual should win most tournaments"
    assert wins[3] > 400, f"Best expected to win often, got {wins[3]}/1000"

    # ── Test 4: Crossover ─────────────────────────────────────────────
    print("\n── Test 4: Single-point crossover ──")
    p1 = [1.0, 2.0, 3.0, 4.0]
    p2 = [10.0, 20.0, 30.0, 40.0]
    c1, c2 = evolver.crossover(p1, p2)
    print(f"Parent 1: {p1}")
    print(f"Parent 2: {p2}")
    print(f"Child 1:  {c1}")
    print(f"Child 2:  {c2}")
    # Each child should be a mix of both parents
    assert len(c1) == 4
    assert len(c2) == 4
    # Children should differ from each parent
    assert c1 != p1 or c2 != p2, "At least one child should differ"

    # ── Test 5: Mutation ──────────────────────────────────────────────
    print("\n── Test 5: Gaussian mutation ──")
    original = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
    mutated = evolver.mutate(original.copy(), mutation_rate=0.5, value_range=(-10.0, 10.0))
    print(f"Original: {[round(x, 2) for x in original]}")
    print(f"Mutated:  {[round(x, 2) for x in mutated]}")
    # With 50% rate on 10 genes, some should change
    changed = sum(1 for a, b in zip(original, mutated) if a != b)
    print(f"Genes changed: {changed}/10")
    assert changed > 0, "Some genes should have mutated"

    # ── Test 6: Fitness history ───────────────────────────────────────
    print("\n── Test 6: Fitness history is monotonic-ish ──")
    # Best fitness should not decrease (elitism)
    for i in range(1, len(result.fitness_history)):
        assert result.fitness_history[i] >= result.fitness_history[i - 1] - 1e-9, (
            f"Best fitness decreased at gen {i}"
        )
    print("Fitness history is non-decreasing ✅")

    print("\n✅ All evolver tests passed!")