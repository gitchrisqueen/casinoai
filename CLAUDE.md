# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

CasinoAI tests casino betting strategies in a systemized way: parse strategy PDFs (`pdfs/`) into machine-executable `StrategySpec`s, verify an LLM agent conforms to each strategy via a deterministic oracle, backtest strategies with Monte Carlo simulation, and finally measure performance against live/demo casino tables. The full roadmap, hypotheses (H1–H3), and phase breakdown live in [PLAN.md](PLAN.md) — read it before making architectural decisions.

**Current state (2026-07-24):** Phases 0–7 complete — see [docs/synthesis.md](docs/synthesis.md) for the full findings. All four game engines (roulette, baccarat, blackjack, craps), the oracle, conformance harness (+ parallel matrix), backtester, and live/demo adapter are built and tested. All five strategy books reviewed, approved (`strategies/approved/`), and backtested — every one negative-EV, matching house-edge theory. Procedural systems are **registered machines** in `casinoai/rules/library.py`, each verified against its book's worked examples. H2 conformance matrix run across deepseek-v4-flash / kimi-k2.6 / gpt-5-mini; unaided, no model hits the 99% target on the complex state machines, but the **facts-level Session Ledger** (`--ledger facts`: deterministic state fed back each round via each machine's `state_view()`) lifts pooled conformance 77%→91% with the hard specs gaining +14 to +36pp. **H3b complete:** ≥10 live free-play demo sessions per focus strategy are done (20 total; adapter now auto-plays FREE demo tables hands-free). Both books' headline claims are **refuted** — Power Baccarat won 10/10 sessions (+87.7u) and Power Pro Roulette 8/10 (−43.8u), but the high win rate is an artefact of asymmetric stop-win/stop-loss rules, not an edge, and the results are consistent with the house edge (H3a) within 2σ. **Remaining:** Phase 8 — research-driven strategy discovery (awaiting go-ahead).

## Ground rules

- **Never commit secrets.** `.env` must stay untracked (`git rm --cached .env` if it reappears); update `.env.example` when adding a new variable instead.
- **Determinism is sacred.** Game engines and the rule-engine oracle must be pure and seeded — no wall-clock, no unseeded RNG, no LLM calls. Only `casinoai/agents/` talks to LLMs.
- **No silent guessing during extraction.** If a strategy PDF is ambiguous, record it in the spec's `ambiguities[]` for human review — don't invent rules.
- **Live play is demo/free-play mode only, human-initiated, with hard bet/session limits enforced in code.** Never build automation that wagers real money or bypasses casino bot-detection.
- **Report results honestly.** Most betting systems lose to the house edge; the deliverable is accurate measurement, not favorable numbers.

## Environment & providers

Copy `.env.example` to `.env` and fill in:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | OpenAI models |
| `ANTHROPIC_API_KEY` | Claude models |
| `OLLAMA_BASE_URL` | Local Ollama server (default `http://localhost:11434`) — no key needed |
| `CASINOAI_DEFAULT_MODEL` | Default model id (LiteLLM naming, e.g. `anthropic/claude-sonnet-5`, `openai/gpt-5.2`, `ollama/llama4`) |

All LLM access goes through the gateway in `casinoai/llm/` (LiteLLM-based). Never call a provider SDK directly from feature code — the gateway provides structured output, retries, and cost logging uniformly across providers. Model choice is always a parameter, never hardcoded, because comparing models is part of the experiment design.

## Commands

Python 3.12, managed with `uv`:

```bash
uv sync                      # install deps
uv run pytest                # full test suite
uv run pytest tests/engines  # engine tests only (fast, no LLM)
uv run ruff check --fix .    # lint
uv run ruff format .         # format
```

Pipeline entry points (as phases land, keep this list current):

```bash
uv run casinoai parse pdfs/Casino_Guides/RouletteLadder.pdf   # PDF → cached markdown
uv run casinoai extract <parsed-doc> --model <model>          # markdown → StrategySpec
uv run casinoai review <spec>                                 # human approval gate
uv run casinoai conform <spec> --model <model> --rounds 1000  # H2 conformance run
uv run casinoai backtest <spec> --rounds 1000000 --seeds 30   # H3a Monte Carlo
```

Tests that need an LLM are marked `@pytest.mark.llm` and skipped by default; run them with `uv run pytest -m llm` (uses Ollama unless a model is specified, to keep costs at zero).

## Architecture map

| Path | Role | LLM? |
|------|------|------|
| `casinoai/llm/` | Provider gateway (OpenAI / Anthropic / Ollama) | — |
| `casinoai/parsing/` | PDF → markdown (Docling), cached in `data/parsed/` | no |
| `casinoai/strategies/` | `StrategySpec` Pydantic schema, extraction, review CLI | extraction only |
| `casinoai/engines/` | Seeded game simulators (roulette, baccarat, craps, blackjack) | never |
| `casinoai/rules/` | Compiles StrategySpec → deterministic oracle | never |
| `casinoai/agents/` | LLM decision agents | yes |
| `casinoai/harness/` | Conformance testing: agent vs. oracle | yes |
| `casinoai/backtest/` | Monte Carlo runner + metrics (DuckDB/Parquet) | never |
| `casinoai/live/` | Playwright demo-play adapter | yes |
| `strategies/approved/` | Human-approved specs (YAML, committed) | — |
| `data/` | Parsed docs + results (gitignored) | — |
| `legacy/` | 2023 prototype, reference only — don't extend it | — |

Key invariant: engines and the live adapter emit the **same typed event-stream shape**, so agents cannot distinguish simulation from live play, and conformance results transfer.

## Conventions

- Pydantic v2 models for every cross-module data shape (game state, actions, specs, results); no bare dicts across boundaries.
- Every simulation/conformance run records: seed, model id, spec version, git SHA — reproducibility is a feature under test.
- Property-based tests (`hypothesis`) for engine math: payouts, distributions vs. known house edge.
- Approved `StrategySpec` YAML files are immutable once used in a published run; changes get a new version, never an edit in place.

## Cross-project context
Global rules for every session live in `~/.claude/CLAUDE.md` (sourced from the CQC Boss Vault, `00-Home/CLAUDE.global.md`). The vault is at `$CQC_VAULT` (fallback: `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/CQC Boss Vault`); read it as plain files.
- This project's vault note: `60-Projects/Side-Products.md` (section "CasinoAI") (create it per `00-Home/Vault-Conventions.md` if missing).
- Handoff packets: `80-Handoffs/HO-<date>-<n>-<slug>.md` per `80-Handoffs/Handoff-Protocol.md`.
- Tracker: none recorded.
- Other projects: look them up in `00-Home/Source-Map.md`; write anything another project needs to the vault, not to auto-memory.
- Decisions for Christopher: options with a recommendation, in chat (see `00-Home/Working-With-Christopher.md`).
