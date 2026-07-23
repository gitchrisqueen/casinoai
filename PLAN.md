# CasinoAI — Implementation Plan (2026 Refresh)

## Mission & Hypotheses

**Mission:** Prove that AI can test casino betting strategies in a systemized, reproducible way — from a strategy described in a PDF, all the way to measured performance at a table.

We decompose that into three testable hypotheses:

| # | Hypothesis | How we prove it |
|---|-----------|-----------------|
| **H1** | An LLM can read a casino strategy PDF and extract it into a machine-executable specification with high fidelity. | Extract each PDF into a `StrategySpec`; a human reviewer (and a second-model judge) scores fidelity against the source text. |
| **H2** | An LLM agent can *conform* to a strategy — making the same decisions the strategy dictates, bet after bet. | Conformance harness: replay identical game states to the LLM agent and to a deterministic rule-engine oracle; measure decision-match rate (target ≥ 99%). |
| **H3** | Strategy performance can be measured systematically — first in Monte Carlo simulation, then against live/demo casino tables. | Backtest millions of rounds per strategy (EV, drawdown, risk of ruin); then run the conformant agent against free-play/demo tables via browser automation and compare observed vs. simulated results. |

> **Honest-science note:** the expected outcome for most betting systems is that they do *not* beat the house edge. The value of this project is the *systemized testing capability itself* — the pipeline that turns any strategy document into quantified, reproducible results.

## What changed since the 2023 prototype

The original stack (LangChain `ConversationalRetrievalChain`, Weaviate RAG, Unstructured self-hosted, GPT-3.5, contextionary/sum-transformers containers) has three structural problems:

1. **RAG is the wrong tool for strategies.** A betting strategy is a *program* (conditions → actions), not a corpus to chat with. We need structured extraction into a typed schema, not vector search.
2. **Skeleton agents with no game to play.** The agent classes are empty `pass` stubs, and there is no game engine, no oracle, and no way to score a decision as right or wrong.
3. **Aged dependencies.** Pre-1.0 LangChain APIs, Weaviate v3 client, single hardcoded OpenAI model.

## Target architecture

```
PDF strategy docs
      │
      ▼
[1] Parsing layer ──── Docling / PyMuPDF → markdown + tables
      │
      ▼
[2] Extraction layer ─ LLM structured output → StrategySpec (Pydantic)
      │                                            │
      ▼                                            ▼
[3] Rule engine ────── deterministic executable   Human review gate
      │  (the oracle)     of the StrategySpec     (approve/annotate)
      │
      ├──────────────► [4] Conformance harness (H2)
      │                     LLM agent vs. oracle on identical state streams
      │
      ├──────────────► [5] Monte Carlo backtester (H3a)
      │                     seeded game engines, millions of rounds, metrics
      │
      └──────────────► [6] Live/demo play adapter (H3b)
                            Playwright vs. free-play tables, human-gated
```

### Key components

**LLM gateway (`casinoai/llm/`)** — one interface, three providers, selected by config:
- **OpenAI** via `OPENAI_API_KEY`
- **Anthropic (Claude)** via `ANTHROPIC_API_KEY`
- **Ollama** (local models) via `OLLAMA_BASE_URL` — no key, free bulk runs
- Implemented with **LiteLLM** (or `pydantic-ai`) so every provider gets the same structured-output, retry, cost-tracking, and logging behavior. Model choice is a run parameter, so H1/H2 results can be compared *across* models (e.g., "Claude Sonnet conforms at 99.4%, local Llama at 91%").

**PDF parsing (`casinoai/parsing/`)** — **Docling** (layout-aware, handles the tables these strategy books are full of) with PyMuPDF4LLM fallback. Output: clean markdown per document, cached to `data/parsed/` so parsing runs once per PDF. OCR fallback for scanned pages.

**StrategySpec (`casinoai/strategies/`)** — the heart of the system. A Pydantic schema capturing:
- game type (roulette / blackjack / craps / baccarat), table rules assumed
- bet types used, entry conditions ("after 3 consecutive reds…")
- betting progression (Martingale-style ladders, Fibonacci, flat, custom tables)
- bankroll rules: unit size, stop-loss, stop-win, session limits
- state tracked (streaks, counts, last outcomes)
- `assumptions[]` and `ambiguities[]` — anything the source PDF leaves unclear, surfaced for human review instead of silently guessed

**Rule engine** — compiles a `StrategySpec` into a deterministic decision function `(game_state, session_state) → action`. This is the *oracle*: ground truth for what the strategy says to do. No LLM in the loop.

**Game engines (`casinoai/engines/`)** — pure-Python simulators with seeded RNG (reproducible runs): roulette (EU/US), baccarat, craps, blackjack (configurable shoe/rules). Emit a typed event stream identical in shape to what the live adapter emits, so agents can't tell simulation from live.

**Conformance harness (`casinoai/harness/`)** — pytest-based. Feeds the same seeded state stream to the LLM agent and the oracle; records every divergence with full context (state, expected, actual, model rationale). Outputs a conformance report per (strategy × model): match rate, divergence taxonomy, cost, latency.

**Backtester (`casinoai/backtest/`)** — runs the *oracle* (not the LLM — it's already proven conformant, so we get LLM-fidelity at simulation speed) for N million rounds × M seeds. Metrics: EV per round, house-edge delta, max drawdown, risk of ruin, session win rate, bankroll survival curves. Results in DuckDB/Parquet; HTML report per strategy.

**Live/demo adapter (`casinoai/live/`)** — Playwright-driven play against **free-play/demo-mode** tables. Reads table state from the DOM, feeds the same event stream format, executes the agent's bets. Compares observed results vs. Monte Carlo prediction.
- ⚠️ **Guardrails:** demo/free-play mode by default; real-money automation violates most casino ToS and gambling law in some jurisdictions — any real-money session is human-driven with the agent advising, and hard stop-loss limits are enforced in code.

### Retired from the old stack
- Weaviate + contextionary + sum-transformers containers → replaced by structured extraction + DuckDB (a vector store can return later if we want cross-strategy semantic search; it's not needed to prove the hypotheses)
- LangChain conversational chains → LiteLLM/pydantic-ai structured calls
- Self-hosted Unstructured API → Docling (local, no service)
- Prometheus/Grafana → simple HTML/Parquet reporting until scale demands more

## Phases

### Phase 0 — Housekeeping (½ day)
- **Remove `.env` from git tracking and rotate the keys currently in it** (`git rm --cached .env`; keys are in history — rotate OpenAI/Google credentials). Add `.env.example`.
- Modern Python scaffold: `uv`, `pyproject.toml` (drop `setup.py`/`requirements.txt`), `ruff`, `pytest`, Python 3.12.
- Archive the 2023 prototype under `legacy/` for reference.

### Phase 1 — LLM gateway (1–2 days)
- LiteLLM wrapper with provider configs for OpenAI, Anthropic, Ollama; structured-output helper; per-call cost/token logging.
- Smoke tests: same schema-constrained prompt through all three providers.
- **Exit criteria:** one `complete(model, prompt, schema)` call works against all three backends.

### Phase 2 — PDF parsing + StrategySpec extraction (3–5 days) → proves **H1**
- Docling pipeline over `pdfs/`; cached markdown output.
- `StrategySpec` schema; extraction prompts with the PDF markdown; two-pass extract-then-verify (second model checks the spec against the source and flags mismatches).
- Review CLI: show spec next to source excerpts, approve/annotate; approved specs saved as YAML in `strategies/approved/`.
- **Exit criteria:** 5 strategies (start with `RouletteLadder`, `Mini-MaxRoulette`, `SuperFibonacci`, `PowerBaccarat`, `Formula57Blackjack`) extracted and human-approved.

### Phase 3 — Game engines + rule engine (3–5 days)
- Roulette + baccarat engines first (most of the PDF library); craps/blackjack next.
- Rule-engine compiler for `StrategySpec`; property-based tests (hypothesis lib) for engine correctness (payout math, wheel distribution vs. known house edge).
- **Exit criteria:** oracle plays 1M seeded roulette rounds under RouletteLadder with zero invariant violations, and simulated house edge matches theory within tolerance.

### Phase 4 — Conformance harness (3–4 days) → proves **H2**
- LLM agent that receives (strategy spec + game state + session state) and returns a structured action.
- Divergence recorder + report; run matrix of approved strategies × {GPT, Claude, Ollama-local}.
- **Exit criteria:** conformance matrix published; at least one (strategy, model) pair ≥ 99% decision-match over 1,000 rounds.

### Phase 5 — Monte Carlo backtesting (2–3 days) → proves **H3a**
- Multiprocess runner, DuckDB results store, per-strategy HTML report (EV, drawdown, risk-of-ruin, survival curves), cross-strategy leaderboard.
- **Exit criteria:** all approved strategies backtested ≥ 1M rounds × 30 seeds with published reports.

### Phase 6 — Live/demo play (1–2 weeks) → proves **H3b**
- Playwright adapter for one demo-mode roulette table (DOM read → event stream → bet placement), session recorder, observed-vs-simulated comparison report.
- Human-in-the-loop launch (operator starts each session), enforced session/bet limits.
- **Exit criteria:** ≥ 10 recorded demo sessions for one strategy with a comparison report against its Monte Carlo prediction.

### Phase 7 — Synthesis (2–3 days)
- Final hypothesis report: H1 fidelity scores, H2 conformance matrix, H3 sim-vs-live comparison; model cost/quality tradeoffs; what to build next (more games, more strategies, fine-tuned local model).

### Phase 8 — Strategy discovery from online research (ongoing, post-baseline)
Once the pipeline has a solid baseline from the PDF library, turn it into a strategy-claims testing service for the open web:
- Use research tools (Perplexity, web search) to find betting strategies with **high win-rate claims** — forums, gambling sites, YouTube system sellers, "guaranteed" systems.
- Capture each found strategy as a source document (page snapshot/markdown → same parsing cache), then run it through the standard pipeline: extract → review → conform → backtest.
- Track a claims ledger per strategy: what the promoter claims vs. what the backtest measures. The deliverable is a growing, reproducible scoreboard of tested claims.
- Rationale: the PDF library (Silverthorne etc.) is largely promotional material; the systemized pipeline exists precisely to test hyped claims without risking money or time at a table.

## Proposed repo layout

```
casinoai/
  llm/            # provider gateway (OpenAI, Anthropic, Ollama)
  parsing/        # PDF → markdown (Docling)
  strategies/     # StrategySpec schema, extraction, review CLI
  engines/        # seeded game simulators
  rules/          # StrategySpec → deterministic oracle
  agents/         # LLM decision agents
  harness/        # conformance testing (H2)
  backtest/       # Monte Carlo + metrics (H3a)
  live/           # Playwright demo-play adapter (H3b)
  reports/        # report generation
strategies/approved/   # human-approved YAML specs
data/parsed/           # cached parsed PDFs (gitignored)
data/results/          # DuckDB/Parquet results (gitignored)
pdfs/                  # source strategy PDFs
legacy/                # 2023 prototype
tests/
```

## Risks

- **Extraction ambiguity** — many of these books are informally written; mitigated by `ambiguities[]` + mandatory human review gate (Phase 2), not silent guessing.
- **Live-site variability/ToS** — demo-mode DOMs change and automation may be unwelcome even in free play; treat Phase 6 as best-effort per site, keep the adapter thin, and get explicit go-ahead per target site.
- **LLM cost at harness scale** — conformance runs are per-decision LLM calls; use Ollama for bulk iteration, paid models for the scored runs.
