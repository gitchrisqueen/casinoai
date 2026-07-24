# CasinoAI — Phase 8: Strategy Discovery from Online Research

*Applying the same extract → dedup → backtest pipeline to hyped betting systems
found on the open web, not just the five PDF books.*

**One-line conclusion:** every discovered system that we could backtest loses to
the house edge, exactly as theory predicts; the systems that we could *not*
backtest are the ones whose progression is a stateful algorithm the current
`StrategySpec` schema cannot express — and we say so honestly rather than faking
a number.

## What we did

1. **Research.** Web search for currently-hyped "beat roulette/baccarat" systems
   with concrete, checkable claims (blogs, forums, promo pages, system-seller copy).
2. **Ingest + extract.** Each system's promotional text was ingested through the
   existing discovery pipeline (`casinoai.discovery.ingest_text` →
   `extract_claim`) with a free Ollama Cloud model
   (`ollama-cloud/deepseek-v4-flash`, $0.00 total). The extractor records only the
   promoter's *claims* (win rate, "guaranteed", "beats the house", verbatim quotes).
3. **Dedup.** Each backtestable system was fingerprinted with
   `casinoai.strategies.identity.StrategyRegistry` against the five approved books
   and each other. Board-position differences (red vs black vs dozen) count as
   **distinct**; only the mechanic + selection + progression *shape* collapses.
4. **Backtest where feasible.** Systems whose mechanic maps onto an existing engine
   + the schema were authored as specs under `strategies/discovered/` and run through
   Monte Carlo (`casinoai backtest`). Systems needing a new **registered machine**
   were recorded as such — not backtested, not guessed.

## Discovered systems

| System | Game | Core mechanic | Promoter claim (verbatim) | Source | Dedup verdict | Measured EV/unit |
|---|---|---|---|---|---|---|
| **1-3-2-6 System** | baccarat (Banker) | Positive ladder 1→3→2→6, advance on win, any loss resets | *"riding short winning streaks while keeping losses in check"; "you're rarely playing with your own money at stake"* | [casinobeats.com](https://casinobeats.com/features/1326-betting-strategy/) | **NEW** (distinct from all 5 books; sim 0.23) | **−0.99%** (theory −1.06%) |
| **Paroli (Reverse Martingale)** | roulette (Red, EU) | Multiplier ×2 **on win**, bank & reset after 3 wins | *"turn a series of wins into a large profit while limiting losses"; "far less risky than the Martingale"* | [freebets.com](https://www.freebets.com/casino/roulette/guides/paroli-reverse-martingale-roulette-strategy/) | **NEW** (distinct from Martingale — multiplies on win, not loss; sim 0.30) | **−2.29%** (theory −2.70%) |
| **Martingale (on Red)** | roulette (Red, EU) | Multiplier ×2 **on loss**, reset on win | *"almost fool-proof"; "a guaranteed win over the very short-term"* | [casino.org](https://www.casino.org/roulette/strategy/martingale/) | **SAME SYSTEM** as the prior-run "Martingale on Red" (already in registry) | **−2.56%** (prior run; RoR 58.8%) |
| **Oscar's Grind** | roulette (even-money) | Flat after a loss; **+1 unit after a win**; session ends at +1u | *"a viable long-term strategy"; "all four players finished with profits of $74–$120"* | [roulette77.us](https://roulette77.us/strategies/oscar-grind) | distinct mechanic | **needs machine** |
| **Labouchère (Cancellation)** | roulette (even-money) | Stake = first+last of a running list; cross off 2 on win, append on loss | *"you only need to win 1/3 of your bets to return a profit"* | [outplayed.com](https://outplayed.com/blog/labouchere-betting-system) | distinct mechanic | **needs machine** |
| **D'Alembert** | roulette (even-money) | **+1 unit after a loss, −1 unit after a win**, floored at 1 | *"one of the safest, most sustainable systems"* (source concedes *"It cannot change the house edge"*) | [roulette77.us](https://roulette77.us/strategies/dalembert) | distinct mechanic | **needs machine** |

EV/unit is the fraction of every unit *staked* that the system loses in
expectation; for even-money bets it must converge to the game's house edge
regardless of the progression, because each individual unit staked carries the
same expectation. The backtests confirm this: the estimates land within sampling
noise of the theoretical edge (Banker −1.06%, European even-money −2.70%).

## Measured vs. unmeasured — be explicit

**Measured (3 systems, Monte Carlo, seeded & reproducible):**

- **1-3-2-6 on Banker** — 200 seeds × 5,000 rounds (388,759 hands): EV/unit
  **−0.99%**, session win rate 36.0%, risk of ruin 0.0%. Spec:
  `strategies/discovered/one-three-two-six.yaml`.
- **Paroli on Red** — 200 seeds × 5,000 rounds (384,821 spins): EV/unit
  **−2.29%**, session win rate 19.5%, risk of ruin 6.0%. Spec:
  `strategies/discovered/paroli-reverse-martingale.yaml`.
- **Martingale on Red** — measured by a prior discovery run and left intact:
  EV/unit **−2.56%**, session win rate 38.2%, risk of ruin **58.8%**. The
  "guaranteed short-term win" is genuine *per session* but paid for by rare
  catastrophic losses — the same asymmetric-variance illusion the project
  already documented for Power Baccarat / Power Pro Roulette.

**Unmeasured — needs a registered machine (honest boundary, 3 systems):**

These progressions are *stateful algorithms*, not one of the schema's
`flat / multiplier / fibonacci / ladder / registered` shapes, so the oracle
cannot compile them and we did **not** fabricate an EV:

- **Oscar's Grind** — additive **+1 on win only**, with the next stake capped so a
  win never overshoots the +1-unit session goal. Additive *and* goal-capped.
- **Labouchère** — the stake is the sum of the two ends of a list that is *edited*
  every round (remove two on a win, append one on a loss). List state.
- **D'Alembert** — additive **+1 after loss / −1 after win**, floored at 1 unit.

Building these as reviewed machines in `casinoai/rules/library.py` (each unit-tested
against a worked example, the same bar the five books had to clear) is the
follow-up needed to backtest them. Theory says all three are negative-EV; that
prediction is stated, not measured.

## Claims vs. reality

The extractor captured what the promoters actually say. Notably, the honest
sources undercut their own hype: the Paroli, Martingale, and D'Alembert pages all
carry explicit disclaimers ("does not change the odds", "cannot beat the house
edge", "cannot change the house edge"). The remaining "claims" are **structural**,
not numeric:

- "You're only risking your winnings" (1-3-2-6, Paroli) — true bookkeeping, but
  every unit still carries the house edge; it reshapes *variance*, not
  *expectation*.
- "Win 1/3 of your bets to profit" (Labouchère) — a break-even *threshold*, not a
  predicted win frequency; the extractor literally recorded it as `win_rate: 0.33`,
  which the ledger note flags as a threshold, not a forecast.
- "Guaranteed short-term win" (Martingale) — the one boolean "guaranteed" claim,
  and the backtest shows exactly why it is a trap: 58.8% of sessions ended in ruin.

No discovered system produced a positive measured EV. This matches both
house-edge theory and the Phase 0–7 finding across the five books.

## Artifacts produced

- Claim ledgers (per system, `StrategyClaim` shape): `strategies/claims/*.json`
  (`1-3-2-6-system`, `paroli-reverse-martingale`, `martingale-on-red`,
  `oscars-grind`, `labouchere-cancellation`, `dalembert`).
- Joined scoreboard entries (claim + measured EV + verdict): `data/claims/claim-*.json`,
  rendered to `data/claims/scoreboard.md` (`casinoai claims`).
- Backtestable specs: `strategies/discovered/one-three-two-six.yaml`,
  `strategies/discovered/paroli-reverse-martingale.yaml`.
- Backtest results: `data/results/backtest-1-3-2-6-system-v1.json`,
  `data/results/backtest-paroli-(reverse-martingale)-v1.json`.
- Dedup registry updated to 8 distinct systems: `data/registry/registry.json`.
- Ingested source text (parsing cache): `data/parsed/*` (one per system).

## Honesty notes / limitations

- EV/unit estimates carry sampling noise; the 30-seed first pass on Paroli read
  −1.6% before 200 seeds pulled it to −2.29% (toward the −2.70% edge). The
  headline numbers are the larger runs.
- Bankroll parameters for the discovered specs (session bankroll, max rounds) are
  modeling choices recorded in each spec's `assumptions`/`approval`; they affect
  session win-rate and risk-of-ruin, not EV/unit.
- The Paroli reset-after-3-wins threshold is the classic convention; some
  promoters leave it to player discretion (recorded as an assumption, not a guess).
- "Needs machine" is a real capability gap, not a failure — it is the schema
  drawing an honest line at what it can execute deterministically.
