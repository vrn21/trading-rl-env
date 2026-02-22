"""backend/client.py — QuantReplay communication + Portfolio state.

Two classes:
  Portfolio          : tracks cash, positions, fills for one episode
  QuantReplayClient  : REST (market data) + FIX (order placement)

FIX session config (must match cfg/configSim.txt):
  BeginString  : FIXT.1.1
  SenderCompID : CLIENT_XETRA
  TargetCompID : SIM_XETRA
"""

import logging
import os
import socket
import time
import uuid

import httpx
import simplefix

logger = logging.getLogger(__name__)

# QuantReplay connection config — override via env vars for platform deployment
REST_URL  = os.getenv("QUANTREPLAY_REST_URL", "http://localhost:9050")
FIX_HOST  = os.getenv("QUANTREPLAY_FIX_HOST", "localhost")
FIX_PORT  = int(os.getenv("QUANTREPLAY_FIX_PORT", "9051"))

# Must match cfg/configSim.txt SESSION entries
FIX_SENDER = "CLIENT_XETRA"
FIX_TARGET = "SIM_XETRA"


# ── Portfolio — in-memory episode state ───────────────────────────────────────

class Portfolio:
    """Tracks cash, open positions, and fill history for one episode."""

    def __init__(self, initial_cash: float = 15_000.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, dict] = {}   # {symbol: {qty, avg_price}}
        self.fills: list[dict] = []

    def reset(self, initial_cash: float | None = None) -> None:
        if initial_cash is not None:            # NOTE: "if initial_cash:" fails for 0.0
            self.initial_cash = initial_cash
        self.cash = self.initial_cash
        self.positions = {}
        self.fills = []

    def record_fill(self, symbol: str, side: str, qty: int, price: float) -> None:
        self.cash += -(qty * price) if side == "BUY" else (qty * price)
        pos = self.positions.setdefault(symbol, {"qty": 0, "avg_price": 0.0})
        if side == "BUY":
            total = pos["avg_price"] * pos["qty"] + price * qty
            pos["qty"] += qty
            pos["avg_price"] = total / pos["qty"]
        else:
            pos["qty"] = max(0, pos["qty"] - qty)
        self.fills.append({"symbol": symbol, "side": side, "qty": qty, "price": price})

    def last_price(self, symbol: str) -> float | None:
        """Return the last fill price for a symbol (best proxy for market price)."""
        for fill in reversed(self.fills):
            if fill["symbol"] == symbol:
                return fill["price"]
        return None

    def net_profit(self) -> float:
        """Net profit using last fill prices for open positions."""
        value = self.cash
        for sym, pos in self.positions.items():
            if pos["qty"] > 0:
                px = self.last_price(sym)
                if px:
                    value += pos["qty"] * px
        return value - self.initial_cash

    def to_dict(self) -> dict:
        return {
            "cash":         round(self.cash, 2),
            "net_profit":   round(self.net_profit(), 2),
            "positions":    {s: p for s, p in self.positions.items() if p["qty"] > 0},
            "total_fills":  len(self.fills),
        }


# ── QuantReplayClient — REST + FIX ───────────────────────────────────────────

class QuantReplayClient:
    """Communicates with QuantReplay via REST (admin/listings) and FIX (orders)."""

    def __init__(self):
        self._http = httpx.AsyncClient(base_url=REST_URL, timeout=10.0)
        self._sock: socket.socket | None = None
        self._parser = simplefix.FixParser()
        self._seq = 1

    # ── REST ─────────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Returns True if QuantReplay is up and responding."""
        try:
            return (await self._http.get("/api/venuestatus")).status_code == 200
        except Exception:
            return False

    async def get_listings(self) -> list[str]:
        """Return all tradeable symbols from the XETRA venue.

        REST response: {"listings": [{symbol, venueId, ...}, ...]}
        """
        r = await self._http.get("/api/listings")
        r.raise_for_status()
        data = r.json()
        # Response is {"listings": [...]} — not a flat list
        items = data.get("listings", data) if isinstance(data, dict) else data
        return [item.get("symbol", "") for item in items if item.get("symbol")]

    async def reset_venue(self) -> bool:
        """Reset QuantReplay venue state (clears order book for new episode).

        POST /api/reset — resets live market state from database settings.
        """
        try:
            r = await self._http.post("/api/reset")
            return r.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._http.aclose()

    # ── FIX ──────────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open FIX socket and perform Logon handshake.

        FIXT.1.1 Logon requires: EncryptMethod(98), HeartBtInt(108), DefaultApplVerID(1137).
        """
        self._sock = socket.create_connection((FIX_HOST, FIX_PORT), timeout=10)
        self._sock.settimeout(5.0)
        msg = self._build("A")                   # Logon
        msg.append_pair(98, "0")                 # EncryptMethod = None
        msg.append_pair(108, "30")               # HeartBtInt = 30s
        msg.append_pair(1137, "9")               # DefaultApplVerID = FIX50SP2
        self._send(msg)
        # Wait for Logon ACK from server
        self._wait_for_logon()
        self._sock.settimeout(0.5)               # back to non-blocking-ish for polling

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._send(self._build("5"))     # Logout
            except Exception:
                pass
            self._sock.close()
            self._sock = None

    def place_order(self, symbol: str, side: str, qty: int, price: float) -> str:
        """Send NewOrderSingle (35=D). Returns ClOrdID for tracking."""
        oid = uuid.uuid4().hex[:8]
        msg = self._build("D")
        msg.append_pair(11, oid)                 # ClOrdID
        msg.append_pair(21, "1")                 # HandlInst = AutoExec
        msg.append_pair(55, symbol)              # Symbol
        msg.append_pair(54, "1" if side == "BUY" else "2")  # Side
        msg.append_pair(38, str(qty))            # OrderQty
        msg.append_pair(40, "2")                 # OrdType = Limit
        msg.append_pair(44, f"{price:.4f}")      # Price
        msg.append_pair(60, self._now())         # TransactTime (required)
        msg.append_pair(59, "0")                 # TimeInForce = Day
        self._send(msg)
        logger.info("NewOrderSingle: %s %s %d @ %.4f [%s]", side, symbol, qty, price, oid)
        return oid

    def cancel_order(self, order_id: str, symbol: str, side: str) -> None:
        """Send OrderCancelRequest (35=F).

        Note: qty NOT required per FIX RoE — only ClOrdID, Side, Symbol, TransactTime.
        """
        msg = self._build("F")
        msg.append_pair(11, uuid.uuid4().hex[:8])  # new ClOrdID for this cancel request
        msg.append_pair(41, order_id)               # OrigClOrdID
        msg.append_pair(55, symbol)
        msg.append_pair(54, "1" if side == "BUY" else "2")
        msg.append_pair(60, self._now())             # TransactTime (required)
        self._send(msg)

    def poll_fills(self) -> list[dict]:
        """Read pending ExecutionReports. Returns fills (ExecType=F = Trade).

        ExecType values per FIX spec:
          0 = New, 4 = Canceled, 5 = Replaced, 8 = Rejected, F = Trade
        """
        fills: list[dict] = []
        if not self._sock:
            return fills
        self._sock.setblocking(False)
        try:
            while True:
                try:
                    data = self._sock.recv(4096)
                    if not data:
                        break
                    self._parser.append_buffer(data)
                    while msg := self._parser.get_message():
                        if msg.get(35) == b"8" and msg.get(150) == b"F":  # ExecType = Trade
                            fills.append({
                                "symbol": (msg.get(55) or b"").decode(),
                                "side":   "BUY" if msg.get(54) == b"1" else "SELL",
                                "qty":    int((msg.get(32) or b"0").decode()),
                                "price":  float((msg.get(31) or b"0").decode()),
                            })
                except BlockingIOError:
                    break
        except OSError:
            pass
        finally:
            self._sock.setblocking(True)
            self._sock.settimeout(0.5)
        return fills

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build(self, msg_type: str) -> simplefix.FixMessage:
        m = simplefix.FixMessage()
        m.append_pair(8, "FIXT.1.1")     # BeginString — FIXT transport layer
        m.append_pair(35, msg_type)
        m.append_pair(49, FIX_SENDER)    # SenderCompID = CLIENT_XETRA
        m.append_pair(56, FIX_TARGET)    # TargetCompID = SIM_XETRA
        m.append_pair(34, str(self._seq))
        m.append_pair(52, self._now())   # SendingTime
        self._seq += 1
        return m

    def _send(self, msg: simplefix.FixMessage) -> None:
        if self._sock:
            self._sock.sendall(msg.encode())

    def _now(self) -> str:
        return time.strftime("%Y%m%d-%H:%M:%S", time.gmtime())

    def _wait_for_logon(self, timeout: float = 5.0) -> None:
        """Block until we receive a Logon ACK (MsgType=A) from QuantReplay."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data = self._sock.recv(4096)
                if data:
                    self._parser.append_buffer(data)
                    while msg := self._parser.get_message():
                        if msg.get(35) == b"A":   # Logon ACK
                            logger.info("FIX Logon ACK received from %s", FIX_TARGET)
                            return
            except socket.timeout:
                continue
        logger.warning("FIX Logon ACK not received within %.1fs — proceeding anyway", timeout)
