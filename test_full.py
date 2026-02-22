"""test_full.py — integration test for trading-rl-env.

Tests every layer in order:
  Layer 1: QuantReplay REST API (listings, venuestatus)
  Layer 2: QuantReplay FIX gateway (logon, order, cancel)
  Layer 3: MCP tool layer via hud dev (requires `hud dev` running on :8765)
  Layer 4: Grader logic (PnLGrader, TradeActivityGrader, Grade)

Run with:
  python test_full.py        # layers 1+2+4 (no hud dev needed)
  python test_full.py --all  # all 4 layers (requires hud dev on :8765)
"""

import asyncio
import socket
import sys
import time
import uuid

import httpx
import simplefix

# ── Config ────────────────────────────────────────────────────────────────────
REST_URL   = "http://localhost:9050"
FIX_HOST   = "localhost"
FIX_PORT   = 9051
MCP_URL    = "http://localhost:8765/mcp"
RUN_ALL    = "--all" in sys.argv

# FIX session — must match cfg/configSim.txt
FIX_SENDER = "CLIENT_XETRA"
FIX_TARGET = "SIM_XETRA"

OK   = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
SKIP = "\033[33m~\033[0m"

passed = failed = skipped = 0


def check(name, result, expected=True):
    global passed, failed
    ok = bool(result) == bool(expected)
    print(f"  {OK if ok else FAIL}  {name}")
    if not ok:
        print(f"       got: {result!r}")
    if ok:
        passed += 1
    else:
        failed += 1
    return ok


def skip(name, reason="hud dev not requested"):
    global skipped
    print(f"  {SKIP}  {name}  [{reason}]")
    skipped += 1


def fix_now():
    return time.strftime("%Y%m%d-%H:%M:%S", time.gmtime())


# ── Layer 1 — REST API ───────────────────────────────────────────────────────
async def test_rest():
    print("\n══ Layer 1: QuantReplay REST API ══")
    async with httpx.AsyncClient(base_url=REST_URL, timeout=10) as c:

        r = await c.get("/api/venuestatus")
        check("GET /api/venuestatus → 200", r.status_code == 200)

        r = await c.get("/api/listings")
        check("GET /api/listings → 200", r.status_code == 200)
        data = r.json()
        # Response: {"listings": [{symbol, ...}, ...]}
        items = data.get("listings", data) if isinstance(data, dict) else data
        symbols = [x.get("symbol", "") for x in items]
        check("at least 1 symbol returned", len(symbols) >= 1)
        check("AMZ in symbol list",         "AMZ" in symbols)
        print(f"       symbols: {symbols}")


# ── Layer 2 — FIX Gateway ────────────────────────────────────────────────────
def test_fix():
    print("\n══ Layer 2: FIX Gateway (FIXT.1.1, CLIENT_XETRA → SIM_XETRA) ══")
    seq = [1]

    def build(msg_type):
        m = simplefix.FixMessage()
        m.append_pair(8,  "FIXT.1.1")    # BeginString — FIXT transport
        m.append_pair(35, msg_type)
        m.append_pair(49, FIX_SENDER)    # CLIENT_XETRA
        m.append_pair(56, FIX_TARGET)    # SIM_XETRA
        m.append_pair(34, str(seq[0]))
        m.append_pair(52, fix_now())
        seq[0] += 1
        return m

    try:
        sock = socket.create_connection((FIX_HOST, FIX_PORT), timeout=5)
        sock.settimeout(3.0)
        check("TCP connect to FIX :9051", True)
    except Exception as e:
        check("TCP connect to FIX :9051", False)
        print(f"       {e}")
        return

    try:
        parser = simplefix.FixParser()

        # Logon (requires tag 1137 = DefaultApplVerID)
        logon = build("A")
        logon.append_pair(98,   "0")   # EncryptMethod = None
        logon.append_pair(108,  "30")  # HeartBtInt
        logon.append_pair(1137, "9")   # DefaultApplVerID = FIX50SP2
        sock.sendall(logon.encode())
        check("Logon sent (FIXT.1.1 + tag 1137)", True)

        # Wait for Logon ACK
        try:
            data = sock.recv(4096)
            parser.append_buffer(data)
        except socket.timeout:
            pass
        got_ack = False
        while msg := parser.get_message():
            if msg.get(35) == b"A":
                got_ack = True
        check("Logon ACK (MsgType=A) received", got_ack)

        # Place BUY limit order (far from market, won't fill)
        oid = uuid.uuid4().hex[:8]
        order = build("D")
        order.append_pair(11, oid)
        order.append_pair(21, "1")         # HandlInst
        order.append_pair(55, "AMZ")
        order.append_pair(54, "1")         # BUY
        order.append_pair(38, "10")        # qty
        order.append_pair(40, "2")         # Limit
        order.append_pair(44, "1.00")      # far below market → won't fill
        order.append_pair(60, fix_now())   # TransactTime (required)
        order.append_pair(59, "0")         # Day
        sock.sendall(order.encode())
        check(f"NewOrderSingle sent (id={oid})", True)

        # Poll for ExecutionReport (MsgType=8, ExecType=0 New)
        time.sleep(0.3)
        try:
            data = sock.recv(4096)
            parser.append_buffer(data)
        except (socket.timeout, BlockingIOError):
            pass
        msgs = []
        while m := parser.get_message():
            msgs.append(m)
        check("received ExecutionReport (35=8)", any(m.get(35) == b"8" for m in msgs))
        for m in msgs:
            mt = (m.get(35) or b"").decode()
            et = (m.get(150) or b"").decode()
            print(f"       MsgType={mt} ExecType={et}")

        # Cancel (TransactTime required, no qty needed)
        cancel = build("F")
        cancel.append_pair(11, uuid.uuid4().hex[:8])  # new ClOrdID
        cancel.append_pair(41, oid)                    # OrigClOrdID
        cancel.append_pair(55, "AMZ")
        cancel.append_pair(54, "1")                    # side
        cancel.append_pair(60, fix_now())              # TransactTime (required)
        sock.sendall(cancel.encode())
        check("OrderCancelRequest sent (no qty, with TransactTime)", True)

        # Logout
        sock.sendall(build("5").encode())

    finally:
        sock.close()


# ── Layer 3 — MCP Tool Layer ─────────────────────────────────────────────────
async def test_mcp_tools():
    print("\n══ Layer 3: MCP Tool Layer (hud dev on :8765) ══")

    expected_tools = {
        "list_symbols", "get_last_price", "get_portfolio",
        "place_order", "cancel_order", "poll_fills",
    }

    if not RUN_ALL:
        for name in sorted(expected_tools) + ["placed order fills portfolio"]:
            skip(name)
        return

    import hud
    from hud import Environment
    env = Environment("trading")
    env.connect_url(MCP_URL)

    async with env:
        tools = env.as_tools()
        tool_names = {t.name for t in tools if not t.name.startswith("_")}
        print(f"       registered: {sorted(tool_names)}")
        check("all expected tools present", expected_tools.issubset(tool_names))

        r = await env.call_tool("list_symbols")
        check("list_symbols → symbols list", "symbols" in r and len(r["symbols"]) >= 1)

        r = await env.call_tool("get_last_price", symbol="AMZ")
        check("get_last_price → has symbol+last_price keys",
              "symbol" in r and "last_price" in r)

        r = await env.call_tool("get_portfolio")
        check("get_portfolio → cash field",      "cash" in r)
        check("get_portfolio → net_profit field", "net_profit" in r)

        r = await env.call_tool("place_order", symbol="AMZ", side="BUY", qty=5, price=1.00)
        check("place_order → order_id returned", "order_id" in r)
        oid = r.get("order_id", "")

        r = await env.call_tool("poll_fills")
        check("poll_fills → fills + count", "fills" in r and "count" in r)

        if oid:
            r = await env.call_tool("cancel_order", order_id=oid, symbol="AMZ", side="BUY")
            check("cancel_order → cancelled id", r.get("cancelled") == oid)


# ── Layer 4 — Grader Logic ───────────────────────────────────────────────────
def test_grader():
    print("\n══ Layer 4: PnLGrader + TradeActivityGrader + Grade ══")
    from backend.client import Portfolio
    from grading import Grade, PnLGrader, TradeActivityGrader

    # PnLGrader: zero profit
    p = Portfolio(initial_cash=15_000)
    g = PnLGrader.grade(weight=1.0, portfolio=p, initial_cash=15_000, target_profit=300)
    check("zero profit → PnLGrader score 0.0", g.score == 0.0)

    # PnLGrader: full profit
    p.record_fill("AMZ", "BUY",  100, 150.0)
    p.record_fill("AMZ", "SELL", 100, 153.0)  # $300 profit
    g = PnLGrader.grade(weight=1.0, portfolio=p, initial_cash=15_000, target_profit=300)
    check("profit=300, target=300 → PnLGrader 1.0", abs(g.score - 1.0) < 1e-6)
    print(f"       actual_profit={p.net_profit():.2f}")

    # PnLGrader: partial
    p2 = Portfolio(initial_cash=15_000)
    p2.record_fill("AMZ", "BUY",  100, 150.0)
    p2.record_fill("AMZ", "SELL", 100, 151.5)  # $150 → 0.5
    g2 = PnLGrader.grade(weight=1.0, portfolio=p2, initial_cash=15_000, target_profit=300)
    check("profit=150, target=300 → PnLGrader 0.5", abs(g2.score - 0.5) < 1e-6)

    # TradeActivityGrader: no fills
    p_empty = Portfolio(initial_cash=15_000)
    ta = TradeActivityGrader.grade(weight=1.0, portfolio=p_empty)
    check("no fills → TradeActivityGrader 0.0", ta.score == 0.0)

    # TradeActivityGrader: round trip
    ta2 = TradeActivityGrader.grade(weight=1.0, portfolio=p)
    check("buy+sell fills → TradeActivityGrader 1.0", ta2.score == 1.0)

    # Combined Grade (0.8 PnL + 0.2 activity)
    grade = Grade.from_subscores([
        PnLGrader.grade(weight=0.8, portfolio=p, initial_cash=15_000, target_profit=300),
        TradeActivityGrader.grade(weight=0.2, portfolio=p),
    ])
    check("combined grade = 1.0 when both hit", abs(grade.score - 1.0) < 1e-6)
    print(f"       combined score: {grade.score:.4f}, metadata: {grade.metadata}")

    # Portfolio.last_price
    check("last_price returns last sell price", p.last_price("AMZ") == 153.0)
    check("last_price for unknown symbol is None", p.last_price("UNKNOWN") is None)

    # Portfolio.to_dict (no args now)
    d = p.to_dict()
    check("to_dict has required keys",
          all(k in d for k in ["cash", "net_profit", "positions", "total_fills"]))


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print(" trading-rl-env — Full Integration Test")
    print(" Layers 1+2+4" + ("+3 (MCP)" if RUN_ALL else " (add --all for MCP layer)"))
    print("=" * 60)

    await test_rest()
    test_fix()
    await test_mcp_tools()
    test_grader()

    print("\n" + "=" * 60)
    print(f" Results: {passed} passed  {failed} failed  {skipped} skipped")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
