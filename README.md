# Trading RL Environment (`trading-rl-env`)

A high-fidelity market simulation environment for Reinforcement Learning agents, built on the HUD Platform and powered by the **QuantReplay XETRA Matching Engine**. 

Agents interact with a live, continuous double-auction limit order book using standard financial protocols (FIX & REST) to complete realistic trading tasks (like target PnL, VWAP execution, or market making).

## Architecture

The environment is a fully self-contained Docker image designed for headless RL training. It combines three layers running concurrently via `supervisord`:

1. **Market Simulator (Layer 1 & 2):** QuantReplay engine exposing a FIX protocol gateway (`:9051`) for order management and a REST API (`:9050`) for venue status.
2. **PostgreSQL Database:** Embedded and pre-seeded at build time with market schema and historical `AMZ` (Amazon) level-2 market data.
3. **HUD MCP Server (Layer 3):** Python backend providing a standardized RL tool interface. Communicates with the platform via `stdio` using JSON-RPC.

## Agent Capabilities

Agents are equipped with 6 specific tools to interact with the environment:

- `list_symbols()`: Returns available tradable tickers inside the simulation (e.g., `AMZ`).
- `get_last_price(symbol)`: Returns the most recent execution price from the agent's fill history.
- `place_order(symbol, side, qty, price, order_type)`: Sends a `NewOrderSingle` FIX message to the matching engine.
- `cancel_order(order_id)`: Attempts to cancel a resting order via `OrderCancelRequest`.
- `poll_fills()`: Awaits and processes incoming FIX `ExecutionReport` messages to update the local portfolio.
- `get_portfolio()`: Returns current realized profit, available cash, and active holdings.

## Grading System

The environment features a multi-faceted grading system (defined in `grading/graders.py`):
- **PnLGrader (Weight: 80%):** Measures actual realized profit against a scenario-defined target. Formula: `clamp(actual_profit / target, 0, 1.0)`.
- **TradeActivityGrader (Weight: 20%):** Ensures the agent is actively participating. 0.0 for no trades, 0.5 for one side, 1.0 for a complete round trip (buy + sell).

## Scenarios
New scenarios can be registered into the system by defining goals in JSON or inside `tasks/`.
Currently includes:
- `take-profit-basic`: Agent starts with $15,000 cash and must achieve a target un-realized or realized net-profit of $200.

---

## Local Development & Testing

You do NOT need `docker-compose`. The architecture is self-contained.

### 1. Build the Environment
```bash
docker build -f Dockerfile.hud -t trading-rl-env:local .
```

### 2. Run the Container
Map the REST (`9050`) and FIX (`9051`) ports to your host network for testing.
```bash
docker run -d --rm --name trading-env -p 9050:9050 -p 9051:9051 trading-rl-env:local
```

### 3. Verify Health & Connectivity
```bash
# Verify REST API
curl http://localhost:9050/api/listings

# Verify FIX Gateway TCP connection
nc -vz localhost 9051
```

### 4. Run the Python Integration Test
The `test_full.py` script validates layers 1, 2, and 4 (REST connection, FIX order flows, Portfolio logic, and Grading matrices).
```bash
python test_full.py
```

### Stop the Container
```bash
docker stop trading-env
```

---

## Platform Deployment

This project strictly adheres to the HUD Platform specification.
To deploy to the platform directly from the CLI:

```bash
hud deploy trading-rl-env
```

- **Variables:** No external dependencies or environment variables are required. `localhost` is intentionally used internally for inter-process communication.
- **Logging:** All JSON-RPC traffic exits via `stdout`. Non-protocol logs (like postgres/supervisord debug info) are redirected to `/dev/null` or `stderr` to prevent JSON corruption during agent sessions.
