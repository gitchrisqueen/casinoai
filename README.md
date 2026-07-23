# CasinoAI

**Systemized AI testing of casino betting strategies** — from a strategy described in a PDF to quantified, reproducible performance results.

Casino strategy books make bold claims ("Win $5,000 a day playing roulette!"). This project builds the machinery to test those claims scientifically:

1. **Parse** — extract each strategy from its PDF into a machine-executable specification (`StrategySpec`) using LLM structured extraction, with a human review gate for ambiguities.
2. **Conform** — prove an LLM agent actually follows the strategy, by replaying identical game states to the agent and to a deterministic rule-engine oracle and measuring decision-match rate.
3. **Measure** — backtest each strategy over millions of simulated rounds (EV, drawdown, risk of ruin), then compare against sessions played on live/demo casino tables via browser automation.

The hypotheses under test and the full roadmap are in **[PLAN.md](PLAN.md)**. Contributor/agent instructions are in **[CLAUDE.md](CLAUDE.md)**.

> **Expectation setting:** most betting systems cannot beat the house edge, and our reports will say so when that's what the data shows. The product is the *testing capability* — a pipeline that turns any strategy document into honest, reproducible numbers.

## How it works

```
PDF ─► Docling parser ─► LLM extraction ─► StrategySpec (YAML, human-approved)
                                                │
                    ┌───────────────────────────┼──────────────────────────┐
                    ▼                           ▼                          ▼
            Rule-engine oracle        Conformance harness           Monte Carlo backtest
            (deterministic truth)     (LLM agent vs. oracle)        (millions of rounds)
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
| Anthropic (Claude) | `anthropic/` | `ANTHROPIC_API_KEY` | Highest quality; deferred until production |

## Quick start

```bash
git clone <repo> && cd Casinoai
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

- `casinoai/` — the package: LLM gateway, PDF parsing, strategy schema, game engines, conformance harness, backtester, live-play adapter (see [CLAUDE.md](CLAUDE.md) for the module map)
- `pdfs/` — source strategy documents (roulette, blackjack, craps, baccarat systems)
- `strategies/approved/` — human-approved, versioned strategy specs
- `data/` — parsed documents and run results (gitignored)
- `legacy/` — the 2023 LangChain/Weaviate prototype, kept for reference

## Responsible use

- Live-table automation targets **demo/free-play mode only** and is human-initiated with hard bet and session limits enforced in code.
- Automating real-money play violates most casinos' terms of service and gambling regulations in many jurisdictions; this project does not do it.
- Nothing here is gambling advice. The math says the house wins; this project measures exactly how.

## Status & early findings

Phases 0–6 built and tested (LLM gateway, PDF parsing, extraction + review, four seeded game engines, deterministic oracle, conformance harness, Monte Carlo backtester, live/demo adapter). Five strategy books extracted, human-reviewed, approved, and backtested over 2,000 seeded sessions each.

**Every system tested loses to the house edge — as expected.** Ranked by EV per unit staked (the honest metric):

| Strategy | Game | EV/unit | Session win rate | Worst drawdown | Risk of ruin |
|----------|------|---------|------------------|----------------|--------------|
| Power Baccarat | baccarat | −0.90% | 88.3% | 91u | 1.8% |
| Super Fibonacci | baccarat | −1.13% | 16.2% | 395u | 21.6% |
| Formula 57 Blackjack | blackjack | −1.15% | 73.6% | 61u | 6.5% |
| Power Pro Roulette | roulette | −2.21% | 84.0% | 58u | 14.6% |
| Mini-Max Roulette | roulette | −3.03% | 29.4% | 21u | 70.5% |

The systems change *variance*, never *expectation*: a high session win rate (Power Baccarat wins 88% of sessions) is funded by rare catastrophic losses. Each EV lands on its game's theoretical house edge. Procedural systems are translated into reviewed, unit-tested state machines in [`casinoai/rules/library.py`](casinoai/rules/library.py), each verified against its book's own worked examples.

The remaining work (H3b live-session collection, Phase 8 online-strategy discovery) is in [PLAN.md](PLAN.md).
