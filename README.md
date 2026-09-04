# CasinoAI

**Systemized AI testing of casino betting strategies** — from a strategy described in a PDF to quantified, reproducible performance results.

Casino strategy books make bold claims ("Win $5,000 a day playing roulette!"). This project builds the machinery to test those claims scientifically:

1. **Parse** — extract each strategy from its PDF into a machine-executable specification (`StrategySpec`) using LLM structured extraction, with a human review gate for ambiguities.
2. **Conform** — prove an LLM agent actually follows the strategy, by replaying identical game states to the agent and to a deterministic rule-engine oracle and measuring decision-match rate.
3. **Measure** — backtest each strategy over thousands of seeded sessions (EV, drawdown, risk of ruin), then compare against sessions played on free-play demo casino tables via browser automation.

The hypotheses under test and the full roadmap are in **[PLAN.md](PLAN.md)**. Contributor/agent instructions are in **[CLAUDE.md](CLAUDE.md)**.

> **Expectation setting:** most betting systems cannot beat the house edge, and our reports will say so when that's what the data shows. The product is the *testing capability* — a pipeline that turns any strategy document into honest, reproducible numbers.

## How it works

```
PDF ─► PDF parser ──► LLM extraction ─► StrategySpec (YAML, human-approved)
                                                │
                    ┌───────────────────────────┼──────────────────────────┐
                    ▼                           ▼                          ▼
            Rule-engine oracle        Conformance harness           Monte Carlo backtest
            (deterministic truth)     (LLM agent vs. oracle)        (2,000 seeded sessions)
                    │                                                      │
                    └────────────► Live/demo play (Playwright) ◄───────────┘
                                   observed vs. predicted results
```

## Multi-provider LLM support

Every LLM step runs against your choice of provider, so results can be compared across models:

| Provider | Model id prefix | Config | Notes |
|----------|-----------------|--------|-------|
| Ollama (local) | `ollama/` | `OLLAMA_BASE_URL` | Local models, zero cost |
| Ollama Cloud | `ollama-cloud/` | `OLLAMA_API_KEY` | Flat-rate hosted models (Kimi, GLM, DeepSeek…) — ideal for bulk runs |
| OpenAI | `openai/` | `OPENAI_API_KEY` | Cheap paid runs (e.g. `openai/gpt-5-mini`) |
| Anthropic (Claude) | `anthropic/` | `ANTHROPIC_API_KEY` | Wired in the gateway; not used in any of the recorded runs |

## Quick start

```bash
git clone https://github.com/gitchrisqueen/casinoai.git && cd casinoai
uv sync
cp .env.example .env   # add your API keys

# Parse a strategy PDF and extract its spec (two-pass extract + verify)
uv run casinoai parse pdfs/Casino_Guides/PowerProRoulette-book.pdf
uv run casinoai extract data/parsed/PowerProRoulette-book-66455d29.json --model ollama-cloud/kimi-k2.6:cloud

# Review/approve, then measure
uv run casinoai review data/specs/fletcher\'s-power-pro-roulette.yaml --show
uv run casinoai conform strategies/approved/power-pro-roulette-v2.yaml --model openai/gpt-5-mini --rounds 100
uv run casinoai backtest strategies/approved/power-pro-roulette-v2.yaml --rounds 1000 --seeds 2000
uv run casinoai report   # cross-strategy leaderboard + H2 conformance matrix

# Live/demo validation (human-operated, demo tables only)
uv run casinoai live strategies/approved/power-pro-roulette-v2.yaml --i-am-playing-a-free-demo-table
```

## Repository layout

- `casinoai/` — the package: LLM gateway, PDF parsing (PyMuPDF4LLM, or Docling when installed), strategy schema, game engines, rule library and oracle, conformance harness, backtester, live/demo adapter, Phase 8 discovery (see [CLAUDE.md](CLAUDE.md) for the module map)
- `pdfs/` — source strategy documents (roulette, blackjack, craps, baccarat systems). Gitignored (`pdfs/*` in `.gitignore`), so `parse`/`extract` need your own copies.
- `strategies/approved/` — the five human-approved, versioned strategy specs
- `strategies/discovered/`, `strategies/claims/` — Phase 8: Phase 8 specs for systems found online, plus recorded promoter claims for those six systems and for the two focus books (Power Baccarat, Power Pro Roulette) (see [docs/phase8_discovery.md](docs/phase8_discovery.md))
- `configs/table_layouts/` — calibrated click layouts for the demo tables the live adapter has been run against
- `docs/` — [synthesis.md](docs/synthesis.md) (findings), [live_adapter.md](docs/live_adapter.md), [phase8_discovery.md](docs/phase8_discovery.md)
- `scripts/` — live/demo session helpers (see [scripts/README.md](scripts/README.md))
- `tests/` — 226 pytest tests; 218 run offline, 8 are marked `llm` and skipped by default
- `data/` — parsed documents and run results (gitignored)
- `legacy/` — the 2023 LangChain/Weaviate prototype, kept for reference

## Responsible use

- Live-table automation targets **demo/free-play mode only**. Sessions are started by a human; the `live` command requires an explicit `--i-am-playing-a-free-demo-table` flag, the hands-free auto-play mode asks you to confirm the table is in free mode first, real-money launcher URLs are refused, and hard bet, round and stop-loss caps are enforced in [`casinoai/live/guard.py`](casinoai/live/guard.py) regardless of what the strategy says.
- Automating real-money play violates most casinos' terms of service and gambling regulations in many jurisdictions; this project does not do it.
- Nothing here is gambling advice. The math says the house wins; this project measures exactly how.

## Status & early findings

Phases 0–7 of [PLAN.md](PLAN.md) are built and tested (LLM gateway, PDF parsing, extraction + review, four seeded game engines, deterministic oracle, conformance harness, Monte Carlo backtester, live/demo adapter, synthesis). Five strategy books extracted, human-reviewed, approved, and backtested over 2,000 seeded sessions each (about 400k rounds in total across the five). The backtests are deterministic: `uv run casinoai backtest <spec> --rounds 1000 --seeds 2000` reproduces every row below to the printed precision.

**Every system tested loses to the house edge — as expected.** Ranked by EV per unit staked (the honest metric):

| Strategy | Game | EV/unit | Session win rate | Worst drawdown | Risk of ruin |
|----------|------|---------|------------------|----------------|--------------|
| Power Baccarat | baccarat | −0.90% | 88.3% | 91u | 1.8% |
| Super Fibonacci | baccarat | −1.13% | 16.2% | 395u | 21.6% |
| Formula 57 Blackjack | blackjack | −1.15% | 73.6% | 61u | 6.5% |
| Power Pro Roulette | roulette | −2.21% | 84.0% | 58u | 14.6% |
| Mini-Max Roulette | roulette | −3.03% | 29.4% | 21u | 70.5% |

The systems change *variance*, never *expectation*: a high session win rate (Power Baccarat wins 88% of sessions) is funded by rare catastrophic losses. Each EV lands near its game's theoretical house edge. Procedural systems are translated into reviewed, unit-tested state machines in [`casinoai/rules/library.py`](casinoai/rules/library.py), three of them (Formula 57, Power Baccarat, Mini-Max) are replayed against their books' worked tables in `tests/rules/`; the Super Fibonacci and Power Pro machines are unit-tested against the rules as approved.

**Conformance (H2):** no model reaches the 99% decision-match target unaided on the complex state machines. Feeding the oracle's own state back to the agent each round (`--ledger facts`) lifts pooled conformance from 77% to 91%. The per-model matrix (deepseek-v4-flash, gpt-5-mini, kimi-k2.6) is in [docs/synthesis.md](docs/synthesis.md).

**Live demo play (H3b):** 20 sessions on free-play demo tables, played by the hands-free auto-play adapter after a human started each run and confirmed FREE mode, 10 each for Power Baccarat (10/10 sessions won, +87.7u) and Power Pro Roulette (8/10 won, −43.8u). The high win rates come from asymmetric stop-win/stop-loss rules, not an edge; the results are consistent with the backtests. Details and caveats (20 sessions is underpowered) are in [docs/synthesis.md](docs/synthesis.md). The session recordings live in `data/` and are not committed.

**Phase 8 (discovery from online sources)** has measured three online systems, all negative-EV: 1-3-2-6 (−0.99%) and Paroli (−2.29%) specced under `strategies/discovered/`, plus Martingale on Red (−2.56%) from an earlier discovery run; three more (Oscar's Grind, Labouchère, D'Alembert) need new rule-library machines before they can be measured and are recorded as unmeasured. See [docs/phase8_discovery.md](docs/phase8_discovery.md).

Not done: the three Phase 8 systems above, hands-free blackjack auto-play (the Pragmatic Play demo reader and manual play are capture-verified, but the fixed-click driver cannot make hit/stand/double/split decisions, so Formula 57 runs in manual mode only; see [configs/table_layouts/README.md](configs/table_layouts/README.md)), a craps strategy (readers exist, no approved spec), and any live session beyond the 20 recorded.
