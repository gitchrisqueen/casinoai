"""Parallel conformance matrix (H2): run many (spec × model × seed) cells at once.

Each cell is one sequential session (round N needs round N-1's outcome, so it
can't be parallelized internally), but cells are independent, so we fan them out
across a thread pool. The work is network-bound (LLM calls), so threads give a
near-linear speedup up to the provider's concurrency limit.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import BaseModel

from casinoai.harness.conformance import ConformanceReport, run_conformance
from casinoai.strategies import load_spec
from casinoai.strategies.spec import StrategySpec

DEFAULT_RESULTS_DIR = Path("data/results")


class MatrixCellSpec(BaseModel):
    spec_path: str
    model: str
    rounds: int
    seed: int


def _save_report(report: ConformanceReport, results_dir: Path) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    slug = report.strategy.lower().replace(" ", "-")
    model_slug = report.model.replace("/", "_").replace(":", "_")
    out = (
        results_dir / f"conformance-{slug}-v{report.spec_version}-{model_slug}-s{report.seed}.json"
    )
    out.write_text(report.model_dump_json(indent=2))


def run_matrix(
    spec_paths: list[str],
    models: list[str],
    rounds: int = 30,
    seeds: list[int] | None = None,
    max_workers: int = 6,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    on_done=None,
) -> list[ConformanceReport]:
    """Run the full (spec × model × seed) grid concurrently. Returns every
    ConformanceReport (failed cells are dropped with a note via on_done)."""
    seeds = seeds or [0]
    specs: dict[str, StrategySpec] = {p: load_spec(p) for p in spec_paths}

    cells = [
        MatrixCellSpec(spec_path=p, model=m, rounds=rounds, seed=s)
        for p in spec_paths
        for m in models
        for s in seeds
    ]

    def run_cell(cell: MatrixCellSpec):
        report = run_conformance(
            specs[cell.spec_path], model=cell.model, rounds=cell.rounds, seed=cell.seed
        )
        _save_report(report, results_dir)
        return report

    reports: list[ConformanceReport] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(run_cell, c): c for c in cells}
        for fut in as_completed(futures):
            cell = futures[fut]
            try:
                report = fut.result()
                reports.append(report)
                if on_done:
                    on_done(report, None)
            except Exception as exc:  # keep the grid going if one cell dies
                if on_done:
                    on_done(cell, exc)
    return reports
