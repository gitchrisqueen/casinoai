"""CasinoAI command-line entry point.

Subcommands land as their phases do (see PLAN.md):
parse, extract, review, conform, backtest.
"""

import argparse
import sys
from pathlib import Path


def _cmd_parse(args: argparse.Namespace) -> int:
    from casinoai.parsing import parse_pdf

    target = Path(args.path)
    pdfs = sorted(target.rglob("*.pdf")) if target.is_dir() else [target]
    if not pdfs:
        print(f"No PDFs found under {target}", file=sys.stderr)
        return 1
    for pdf in pdfs:
        doc = parse_pdf(pdf, parser=args.parser, force=args.force)
        print(f"{pdf} -> {doc.markdown_path} [{doc.parser}, {doc.n_chars} chars]")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    from casinoai.parsing import ParsedDoc, parse_pdf
    from casinoai.strategies import extract_strategy, save_spec

    path = Path(args.path)
    if path.suffix == ".json":
        parsed = ParsedDoc.model_validate_json(path.read_text())
    else:
        parsed = parse_pdf(path)
    result = extract_strategy(parsed, model=args.model, verify=not args.no_verify)
    spec_path = save_spec(result.spec)
    print(f"Spec: {spec_path}")
    print(f"  game: {result.spec.game}  bets: {[b.bet_type for b in result.spec.bets]}")
    print(f"  progression: {result.spec.progression.kind}")
    if result.spec.ambiguities:
        print(f"  ambiguities ({len(result.spec.ambiguities)}) — needs human review:")
        for a in result.spec.ambiguities:
            print(f"    - {a}")
    for note in result.extraction_notes:
        print(f"  note: {note}")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    from casinoai.strategies import load_spec
    from casinoai.strategies.review import render_spec, review_interactive

    spec = load_spec(Path(args.spec))
    if args.show:
        print(render_spec(spec))
        return 0
    return review_interactive(spec)


def _cmd_backtest(args: argparse.Namespace) -> int:
    from casinoai.backtest.runner import backtest, save_summary
    from casinoai.strategies import load_spec

    spec = load_spec(Path(args.spec))
    summary = backtest(spec, seeds=list(range(args.seeds)), max_rounds=args.rounds)
    path = save_summary(summary)
    print(f"Backtest: {summary.strategy} v{summary.spec_version} [{summary.game}]")
    print(f"  sessions: {summary.n_sessions}  rounds: {summary.total_rounds:,}")
    print(f"  EV/unit staked: {summary.ev_per_unit_staked:+.4%}")
    print(f"  session win rate: {summary.session_win_rate:.1%}")
    mean, sd = summary.mean_session_net, summary.stdev_session_net
    print(f"  mean session net: {mean:+.1f}u  (σ {sd:.1f}u)")
    dd, ruin = summary.worst_drawdown_units, summary.risk_of_ruin
    print(f"  worst drawdown: {dd:.1f}u  risk of ruin: {ruin:.1%}")
    print(f"  saved -> {path}")
    return 0


def _cmd_conform(args: argparse.Namespace) -> int:
    from casinoai.harness.conformance import run_conformance
    from casinoai.strategies import load_spec

    spec = load_spec(Path(args.spec))
    report = run_conformance(
        spec, model=args.model, rounds=args.rounds, seed=args.seed, ledger=args.ledger
    )
    results_dir = Path("data/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    slug = report.strategy.lower().replace(" ", "-")
    model_slug = report.model.replace("/", "_").replace(":", "_")
    out = results_dir / (
        f"conformance-{slug}-v{report.spec_version}-{model_slug}-{report.ledger_mode}.json"
    )
    out.write_text(report.model_dump_json(indent=2))
    print(f"Conformance: {report.strategy} v{report.spec_version} × {report.model}")
    print(
        f"  ledger: {report.ledger_mode}  decisions: {report.decisions}  matches: {report.matches}"
    )
    print(f"  match rate: {report.match_rate:.2%}  cost: ${report.total_cost_usd:.4f}")
    print(
        f"  realized EV/unit — oracle: {report.oracle_ev_per_unit:+.2%}  "
        f"agent: {report.agent_ev_per_unit:+.2%}"
    )
    for d in report.divergences[:10]:
        print(f"  ✗ round {d.round_index}: expected {d.expected} got {d.actual} — {d.rationale}")
    if len(report.divergences) > 10:
        print(f"  ... and {len(report.divergences) - 10} more divergences")
    return 0


def _cmd_matrix(args: argparse.Namespace) -> int:
    from casinoai.harness.matrix import run_matrix

    spec_paths = args.specs or sorted(str(p) for p in Path("strategies/approved").glob("*.yaml"))
    models = args.models
    seeds = list(range(args.seeds))
    print(
        f"H2 matrix: {len(spec_paths)} specs × {len(models)} models × {len(seeds)} seeds "
        f"× {args.rounds} rounds, {args.workers} workers"
    )

    def on_done(result, err):
        if err is not None:
            print(
                f"  ✗ {getattr(result, 'spec_path', result)} × "
                f"{getattr(result, 'model', '?')}: {err}"
            )
        else:
            print(
                f"  ✓ {result.strategy} × {result.model} (seed {result.seed}): "
                f"{result.match_rate:.0%} ({result.matches}/{result.decisions})"
            )

    run_matrix(
        spec_paths,
        models,
        rounds=args.rounds,
        seeds=seeds,
        max_workers=args.workers,
        on_done=on_done,
        ledger=args.ledger,
    )
    print("\nMatrix complete — run `casinoai report` for the aggregated table.")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from casinoai.reports.leaderboard import (
        build_leaderboard,
        load_backtests,
        render_markdown,
        write_report,
    )

    summaries = load_backtests()
    if not summaries:
        print("No backtest results in data/results/ — run `casinoai backtest` first.")
        return 1
    rows = build_leaderboard(summaries)
    print(render_markdown(rows))
    path = write_report()
    print(f"\nsaved -> {path}")

    from casinoai.reports import conformance_matrix

    conf_reports = conformance_matrix.load_conformance()
    if conf_reports:
        print()
        print(conformance_matrix.render_markdown(conf_reports))
        conf_path = conformance_matrix.write_report()
        print(f"\nsaved -> {conf_path}")
    return 0


def _cmd_registry(args: argparse.Namespace) -> int:
    from casinoai.strategies import load_spec
    from casinoai.strategies.identity import (
        StrategyRegistry,
        load_approved_specs,
    )

    reg = StrategyRegistry.load()
    if args.seed:
        for spec in load_approved_specs():
            reg.register(spec, f"approved:{spec.name}")
        reg.save()
        print(f"Seeded registry with approved strategies -> {len(reg.entries)} systems.")
    if args.check:
        spec = load_spec(Path(args.check))
        result = reg.check(spec, known_specs=load_approved_specs())
        print(
            f"{spec.name}: {result.status.upper()}"
            + (
                f" (matches '{result.matched_name}': {result.reason})"
                if result.matched_name
                else ""
            )
        )
        return 0
    print(f"Strategy registry — {len(reg.entries)} distinct systems:")
    for e in reg.entries.values():
        print(
            f"  [{e.game}] {e.canonical_name}  fp={e.core_fingerprint}  "
            f"variants={len(e.full_fingerprints)}  sources={len(e.sources)}"
        )
    return 0


def _cmd_track(args: argparse.Namespace) -> int:
    from casinoai.backtest.runner import BacktestSummary
    from casinoai.discovery.claims import StrategyClaim
    from casinoai.live.tracker import build_tracking, render_tracking
    from casinoai.strategies import load_spec

    spec_paths = args.specs or [
        "strategies/approved/power-baccarat-v2.yaml",
        "strategies/approved/power-pro-roulette-v2.yaml",
    ]
    rows = []
    for sp in spec_paths:
        spec = load_spec(Path(sp))
        slug = spec.name.lower().replace(" ", "-")
        bt_path = Path(f"data/results/backtest-{slug}-v{spec.version}.json")
        backtest = (
            BacktestSummary.model_validate_json(bt_path.read_text()) if bt_path.exists() else None
        )
        claim_path = Path(f"strategies/claims/{slug}.json")
        claim = (
            StrategyClaim.model_validate_json(claim_path.read_text())
            if claim_path.exists()
            else None
        )
        rows.append(build_tracking(spec.name, backtest=backtest, claim=claim))
    md = render_tracking(rows)
    print(md)
    out = Path("data/results/tracking.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md + "\n")
    print(f"\nsaved -> {out}")
    return 0


def _cmd_claims(args: argparse.Namespace) -> int:
    from casinoai.discovery import load_claims, render_scoreboard

    entries = load_claims()
    if not entries:
        print("No claims in data/claims/ yet — discover strategies first (Phase 8).")
        return 1
    md = render_scoreboard(entries)
    print(md)
    out = Path("data/claims/scoreboard.md")
    out.write_text(md + "\n")
    print(f"\nsaved -> {out}")
    return 0


def _cmd_live(args: argparse.Namespace) -> int:
    from casinoai.live import SessionLimits
    from casinoai.live.playwright_adapter import OperatorBetPlacer
    from casinoai.live.reader import ManualTableReader
    from casinoai.live.session import run_live_session, save_session
    from casinoai.strategies import load_spec

    spec = load_spec(Path(args.spec))
    print(f"LIVE/DEMO observer session — {spec.name} v{spec.version} [{spec.game}]")
    print("Demo/free-play only. You place each bet by hand on the demo table,")
    print("then type the winning pocket here. Nothing is wagered automatically.\n")
    if not args.i_am_playing_a_free_demo_table:
        print("Refusing to start: pass --i-am-playing-a-free-demo-table to confirm the")
        print("table is in demo/free-play mode and you (a human) are operating it.")
        return 1
    limits = SessionLimits(
        max_bet_units=args.max_bet,
        max_total_stake_units=args.max_bet * 2,
        max_rounds=args.max_rounds,
        stop_loss_units=args.stop_loss,
    )
    session = run_live_session(
        spec,
        ManualTableReader(),
        OperatorBetPlacer(),
        limits,
        table_url=args.table_url,
    )
    path = save_session(session)
    print(f"\nSession ended: {session.stop_reason}")
    print(f"  rounds: {len(session.rounds)}  net: {session.net_units:+.1f}u")
    print(f"  saved -> {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="casinoai",
        description="Systemized testing of casino betting strategies.",
    )
    sub = parser.add_subparsers(dest="command")

    p_parse = sub.add_parser("parse", help="Parse PDF(s) to cached markdown in data/parsed/")
    p_parse.add_argument("path", help="A PDF file or a directory to scan recursively")
    p_parse.add_argument("--parser", choices=["docling", "pymupdf4llm"], default=None)
    p_parse.add_argument("--force", action="store_true", help="Re-parse even if cached")
    p_parse.set_defaults(func=_cmd_parse)

    p_extract = sub.add_parser("extract", help="Extract a StrategySpec from a parsed doc or PDF")
    p_extract.add_argument("path", help="A parsed-doc .json sidecar or a PDF (parsed on demand)")
    p_extract.add_argument("--model", default=None, help="LLM model id (default from env)")
    p_extract.add_argument("--no-verify", action="store_true", help="Skip the verification pass")
    p_extract.set_defaults(func=_cmd_extract)

    p_review = sub.add_parser("review", help="Human approval gate for a draft spec")
    p_review.add_argument("spec", help="Path to a draft spec YAML (data/specs/...)")
    p_review.add_argument("--show", action="store_true", help="Display only, no approval prompt")
    p_review.set_defaults(func=_cmd_review)

    p_conform = sub.add_parser("conform", help="H2 conformance run: LLM agent vs. oracle")
    p_conform.add_argument("spec", help="Path to a spec YAML")
    p_conform.add_argument("--model", default=None, help="LLM model id (default from env)")
    p_conform.add_argument("--rounds", type=int, default=100)
    p_conform.add_argument("--seed", type=int, default=0)
    p_conform.add_argument("--ledger", choices=["none", "facts"], default="none")
    p_conform.set_defaults(func=_cmd_conform)

    p_backtest = sub.add_parser("backtest", help="Monte Carlo backtest of an approved spec")
    p_backtest.add_argument("spec", help="Path to a spec YAML (strategies/approved/...)")
    p_backtest.add_argument("--rounds", type=int, default=10_000, help="Max rounds per session")
    p_backtest.add_argument("--seeds", type=int, default=30, help="Number of seeded sessions")
    p_backtest.set_defaults(func=_cmd_backtest)

    p_matrix = sub.add_parser("matrix", help="Parallel H2 conformance matrix (spec × model × seed)")
    p_matrix.add_argument(
        "--specs", nargs="*", default=None, help="Spec YAMLs (default: all approved)"
    )
    p_matrix.add_argument(
        "--models",
        nargs="+",
        default=["ollama-cloud/deepseek-v4-flash"],
        help="Model ids (default: deepseek-v4-flash — fast, reliable, flat-rate)",
    )
    p_matrix.add_argument("--rounds", type=int, default=30)
    p_matrix.add_argument("--seeds", type=int, default=1, help="Number of seeds per cell")
    p_matrix.add_argument("--workers", type=int, default=6, help="Concurrent cells")
    p_matrix.add_argument(
        "--ledger",
        choices=["none", "facts"],
        default="none",
        help="Feed an authoritative state block to the agent (facts) or not (none)",
    )
    p_matrix.set_defaults(func=_cmd_matrix)

    p_report = sub.add_parser("report", help="Cross-strategy leaderboard from backtest results")
    p_report.set_defaults(func=_cmd_report)

    p_claims = sub.add_parser("claims", help="Phase 8 claims scoreboard (claimed vs. measured)")
    p_claims.set_defaults(func=_cmd_claims)

    p_reg = sub.add_parser("registry", help="Strategy dedup registry (identity by mechanics)")
    p_reg.add_argument("--seed", action="store_true", help="Register all approved strategies")
    p_reg.add_argument("--check", default=None, help="Classify a spec YAML against the registry")
    p_reg.set_defaults(func=_cmd_registry)

    p_track = sub.add_parser("track", help="Claimed vs. simulated vs. live tracking per strategy")
    p_track.add_argument(
        "--specs", nargs="*", default=None, help="Spec YAMLs (default: the two focus strategies)"
    )
    p_track.set_defaults(func=_cmd_track)

    p_live = sub.add_parser(
        "live", help="Human-operated demo/free-play session (H3b, observer mode)"
    )
    p_live.add_argument("spec", help="Path to an approved spec YAML")
    p_live.add_argument("--table-url", default=None, help="URL of the demo table (recorded only)")
    p_live.add_argument("--max-bet", type=float, default=8.0, help="Hard cap per bet (units)")
    p_live.add_argument("--max-rounds", type=int, default=200, help="Hard session length cap")
    p_live.add_argument(
        "--stop-loss", type=float, default=40.0, help="Hard session loss cap (units)"
    )
    p_live.add_argument(
        "--i-am-playing-a-free-demo-table",
        action="store_true",
        help="Required: confirms a human is operating a demo/free-play table",
    )
    p_live.set_defaults(func=_cmd_live)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
