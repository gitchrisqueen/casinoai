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

| Provider | Config | Notes |
|----------|--------|-------|
| OpenAI | `OPENAI_API_KEY` | |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | |
| Ollama | `OLLAMA_BASE_URL` | Local models, zero cost — ideal for bulk conformance runs |

## Quick start

```bash
git clone <repo> && cd Casinoai
uv sync
cp .env.example .env   # add your API keys

# Parse a strategy PDF and extract its spec
uv run casinoai parse pdfs/Casino_Guides/RouletteLadder.pdf
uv run casinoai extract data/parsed/RouletteLadder.md --model anthropic/claude-sonnet-5
uv run casinoai review strategies/drafts/roulette-ladder.yaml

# Test conformance and backtest
uv run casinoai conform strategies/approved/roulette-ladder.yaml --model openai/gpt-5.2 --rounds 1000
uv run casinoai backtest strategies/approved/roulette-ladder.yaml --rounds 1000000 --seeds 30
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

## Status

Currently executing Phase 0–1 of [PLAN.md](PLAN.md): repo modernization (uv, ruff, pytest) and the multi-provider LLM gateway. The 2023 prototype (LangChain + Weaviate RAG ingestion) is being retired to `legacy/`.
