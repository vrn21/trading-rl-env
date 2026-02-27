# Quant Trading Tasks — Hard Taskset Spec (v2)

This is a harder replacement for the earlier task draft.

The old pattern (`hit profit X`) is too easy because the agent can spam one symbol with simple buy/sell loops.  
The new taskset below forces **execution quality**, **risk control**, **inventory control**, and **multi-symbol reasoning** at the same time.

---

## Environment Reality (unchanged)

- Limit-order market with random background flow
- Agent tools: `list_symbols`, `get_listing_rules`, `market_data_snapshot`, `place_order`, `replace_order`, `poll_fills`, `cancel_order`, `get_last_price`, `get_portfolio`
- Graders can use `portfolio.fills`, `portfolio.positions`, `portfolio.cash`, `portfolio.initial_cash`, `portfolio.net_profit()`

No environment API changes are required for this spec.  
Only new scenarios + graders are needed.

---

## Hardness Principles

Every hard task should block these shortcuts:

1. **One lucky trade** → blocked by minimum profitable round trips
2. **All-in sizing** → blocked by max drawdown + max inventory
3. **One-symbol farming** → blocked by symbol coverage + per-symbol profit checks
4. **Messy exits** → blocked by end-flat requirement
5. **Noisy churn** → blocked by profit-factor / edge quality checks

---

## Graders

### Keep Existing

- `PnLGrader`
- `TradeActivityGrader`
- `EndFlatGrader`
- `MaxDrawdownGrader`
- `RoundTripGrader`
- `SymbolsCoveredGrader`

### New Graders (needed for real hardness)

#### `ProfitFactorGrader`

Measures trade quality, not just total profit.

- Build FIFO-matched round-trip PnL per symbol
- `gross_profit = sum(max(pnl, 0))`
- `gross_loss = sum(abs(min(pnl, 0)))`
- `profit_factor = gross_profit / max(gross_loss, 1e-9)`
- Score:
  - `0.0` if `profit_factor <= 1.0`
  - linear to `1.0` at `target_profit_factor`

Simple score:
```python
score = clamp((profit_factor - 1.0) / (target_profit_factor - 1.0), 0.0, 1.0)
```

---

#### `PerSymbolProfitGrader`

Stops single-symbol overfitting.

- Compute realized FIFO PnL per symbol
- Count symbols with `realized_pnl >= min_profit_per_symbol`
- Score:
```python
score = clamp(count_good_symbols / required_symbols, 0.0, 1.0)
```

---

#### `MaxInventoryGrader`

Forces inventory discipline.

- Replay fills and track peak absolute position per symbol (or total, depending on task)
- Score:
  - `1.0` if `peak_inventory <= inventory_limit`
  - linear decay to `0.0` at `2 * inventory_limit`

---

#### `StepBudgetGrader` *(optional; only if framework exposes step/turn count)*

Tests fast tool use without reward hacking.

- Input: `steps_used`, `step_budget`
- Score:
```python
score = 1.0 if steps_used <= step_budget else max(0.0, 1.0 - (steps_used - step_budget) / step_budget)
```

If step count is not available in graders, skip this grader and keep it as a benchmark-side metric.

---

## 5 Hard Tasks (final set)

These 5 are intentionally hard but still simple to describe.

### Task 1 — `maker-discipline`

**What it tests:** patient execution, inventory control, repeated profitable trading

| Parameter | Value |
|---|---|
| Cash | $15,000 |
| Symbol | AMZ |
| Target profit | $180 |
| Min profitable round trips | 8 |
| Target profit factor | 1.6 |
| Max inventory | 80 shares |
| Max drawdown | $250 |
| End state | Flat |

**Prompt**
```text
You are a trader on XETRA. Cash: $15,000.
On AMZ, make at least $180 net profit.
Complete at least 8 profitable round trips.
Keep peak open position at or below 80 shares.
Keep max drawdown at or below $250.
End with zero position.
```

**Graders (weights)**
- `PnLGrader` 0.18
- `RoundTripGrader` 0.24
- `ProfitFactorGrader` 0.22
- `MaxInventoryGrader` 0.16
- `MaxDrawdownGrader` 0.10
- `EndFlatGrader` 0.10

Why this is hard: one big lucky trade will not pass; the agent must repeatedly execute good entries/exits.

---

### Task 2 — `underwater-unwind`

**What it tests:** position rescue, liquidation discipline, recovery under risk limits

| Parameter | Value |
|---|---|
| Initial cash | $35,000 |
| Setup fill | BUY 220 AMZ @ 103 |
| Target profit | $250 |
| Target profit factor | 1.3 |
| Max drawdown | $300 |
| Min profitable round trips | 3 |
| End state | Flat |

**Setup**
```python
portfolio.reset(initial_cash=35_000.0)
portfolio.record_fill("setup", "AMZ", "BUY", 220, 103.0)
```

**Prompt**
```text
You start with an open AMZ long: 220 shares at average 103.
Recover this book and finish with at least $250 net profit.
Keep max drawdown at or below $300.
Complete at least 3 profitable round trips.
End with zero position.
```

**Graders (weights)**
- `PnLGrader` 0.25
- `EndFlatGrader` 0.20
- `MaxDrawdownGrader` 0.20
- `ProfitFactorGrader` 0.20
- `RoundTripGrader` 0.10
- `TradeActivityGrader` 0.05

Why this is hard: the agent starts with bad inventory and must unwind + recover without panic-selling.

---

### Task 3 — `balanced-cross-symbol`

**What it tests:** capital allocation, diversification, per-symbol edge

| Parameter | Value |
|---|---|
| Cash | $20,000 |
| Target profit | $260 |
| Min traded symbols | 3 |
| Required profitable symbols | 2 |
| Min profit per profitable symbol | $60 |
| Max drawdown | $350 |
| End state | Flat |

**Prompt**
```text
You are a trader on XETRA. Cash: $20,000.
Make at least $260 net profit.
Trade at least 3 symbols.
At least 2 symbols must each make $60+ realized profit.
Keep max drawdown at or below $350.
End with zero positions.
```

**Graders (weights)**
- `PnLGrader` 0.20
- `SymbolsCoveredGrader` 0.20
- `PerSymbolProfitGrader` 0.25
- `MaxDrawdownGrader` 0.15
- `EndFlatGrader` 0.10
- `ProfitFactorGrader` 0.10

Why this is hard: it blocks “farm one ticker” behavior and forces balanced book management.

---

### Task 4 — `small-capital-precision`

**What it tests:** quant sizing under very tight capital and risk

| Parameter | Value |
|---|---|
| Cash | $6,000 |
| Target profit | $120 |
| Min profitable round trips | 6 |
| Target profit factor | 1.8 |
| Max drawdown | $120 |
| Max inventory | 35 shares |
| End state | Flat |

**Prompt**
```text
You are a trader on XETRA. Cash: $6,000.
Make at least $120 net profit.
Complete at least 6 profitable round trips.
Keep profit factor at or above 1.8.
Keep max drawdown at or below $120.
Keep peak position at or below 35 shares.
End with zero position.
```

**Graders (weights)**
- `PnLGrader` 0.20
- `RoundTripGrader` 0.20
- `ProfitFactorGrader` 0.20
- `MaxDrawdownGrader` 0.20
- `MaxInventoryGrader` 0.10
- `EndFlatGrader` 0.10

Why this is hard: tiny account + tight drawdown means sizing mistakes fail immediately.

---

### Task 5 — `quant-gauntlet-hard`

**What it tests:** full-desk behavior under many constraints

| Parameter | Value |
|---|---|
| Cash | $25,000 |
| Target profit | $450 |
| Min traded symbols | 3 |
| Required profitable symbols | 3 |
| Min profit per profitable symbol | $70 |
| Min profitable round trips | 10 |
| Target profit factor | 1.8 |
| Max drawdown | $400 |
| Max inventory | 120 shares per symbol |
| End state | Flat |
| Optional step budget | 45 turns |

**Prompt**
```text
You are a trader on XETRA. Cash: $25,000.
Make at least $450 net profit.
Trade at least 3 symbols.
Each of those 3 symbols must make at least $70 realized profit.
Complete at least 10 profitable round trips.
Keep profit factor at or above 1.8.
Keep max drawdown at or below $400.
Keep peak position per symbol at or below 120 shares.
End with zero positions.
```

**Graders (weights, no step budget)**
- `PnLGrader` 0.18
- `SymbolsCoveredGrader` 0.12
- `PerSymbolProfitGrader` 0.12
- `RoundTripGrader` 0.14
- `ProfitFactorGrader` 0.14
- `MaxDrawdownGrader` 0.14
- `MaxInventoryGrader` 0.08
- `EndFlatGrader` 0.08

**If step count is available**
- Add `StepBudgetGrader` with weight `0.08`
- Reduce `PnLGrader` to `0.14` and `ProfitFactorGrader` to `0.10`

Why this is hard: model must do good execution, good risk control, good allocation, and good cleanup in one episode.

---

## Quick Calibration (sanity check)

- A generic untrained model that does “buy then sell +1” repeatedly should fail Tasks 1–5 on:
  - round-trip count quality,
  - profit factor,
  - drawdown,
  - inventory limits,
  - diversification requirements.
- A trained policy should improve gradually:
  - first passes `small-capital-precision`,
  - then `maker-discipline` and `balanced-cross-symbol`,
  - then `underwater-unwind`,
  - finally `quant-gauntlet-hard`.

---

## Implementation Scope

### Files

```text
grading/graders.py      # add: ProfitFactorGrader, PerSymbolProfitGrader, MaxInventoryGrader (+ optional StepBudgetGrader)
grading/__init__.py     # export new graders
tasks/quant_tasks.py    # add these 5 scenarios
tasks/__init__.py       # import quant_tasks
env.py                  # register quant_tasks.register(...)
```

### Important constraints

- No admin APIs exposed to agent
- No direct reward/grade visibility in tools
- Keep prompts short (no strategy hints)
- Use strict binary checks where needed (`EndFlat`, min symbols) to prevent score hacking

---

## Final Note

If you want this benchmark to stay hard over time, rotate parameter values by seed (targets, limits, setup positions) so the model cannot memorize fixed numbers.
