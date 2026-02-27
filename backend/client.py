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
from urllib.parse import quote

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

_ORDER_TYPE_TO_FIX = {
    "LIMIT": "2",
    "MARKET": "1",
}

_TIME_IN_FORCE_TO_FIX = {
    "DAY": "0",
    "GTC": "1",
    "IOC": "3",
    "FOK": "4",
    "GTD": "6",
}

_SIDE_TO_FIX = {
    "BUY": "1",
    "SELL": "2",
    "SELL_SHORT": "5",
    "SELL_SHORT_EXEMPT": "6",
}

_FIX_SIDE_TO_TEXT = {
    "1": "BUY",
    "2": "SELL",
    "5": "SELL_SHORT",
    "6": "SELL_SHORT_EXEMPT",
}

_FIX_EXEC_TYPE_TO_TEXT = {
    "0": "NEW",
    "4": "CANCELED",
    "5": "REPLACED",
    "8": "REJECTED",
    "C": "EXPIRED",
    "F": "TRADE",
}

_FIX_ORD_STATUS_TO_TEXT = {
    "0": "NEW",
    "1": "PARTIALLY_FILLED",
    "2": "FILLED",
    "4": "CANCELED",
    "5": "REPLACED",
    "8": "REJECTED",
}

_FIX_MD_ENTRY_TYPE_TO_TEXT = {
    "0": "BID",
    "1": "OFFER",
    "2": "TRADE",
    "7": "LOW",
    "8": "HIGH",
    "H": "MID",
}

_MD_ENTRY_TYPE_TO_FIX = {
    "BID": "0",
    "OFFER": "1",
    "TRADE": "2",
    "LOW": "7",
    "HIGH": "8",
    "MID": "H",
}

_FIX_MD_UPDATE_ACTION_TO_TEXT = {
    "0": "NEW",
    "1": "CHANGE",
    "2": "DELETE",
}

_FIX_MD_REJECT_REASON_TO_TEXT = {
    "0": "UNKNOWN_SYMBOL",
    "1": "DUPLICATE_REQUEST_ID",
}

_FIX_SECURITY_STATUS_TO_TEXT = {
    "2": "HALT",
    "3": "RESUME",
}

_FIX_TRADING_PHASE_TO_TEXT = {
    "2": "OPENING_AUCTION",
    "3": "OPEN",
    "4": "CLOSING_AUCTION",
    "5": "POST_TRADING",
    "6": "INTRADAY_AUCTION",
    "10": "CLOSED",
}

_MD_SUBSCRIPTION_REQUEST_TO_FIX = {
    "SNAPSHOT": "0",
    "SUBSCRIBE": "1",
    "UNSUBSCRIBE": "2",
}

_MD_UPDATE_TYPE_TO_FIX = {
    "SNAPSHOT": "0",
    "FULL": "0",
    "INCREMENTAL": "1",
}

_MD_DEPTH_TO_FIX = {
    "FULL": "0",
    "TOP": "1",
}

_SECURITY_SUBSCRIPTION_REQUEST_TO_FIX = {
    "SNAPSHOT": "0",
    "SUBSCRIBE": "1",
    "UNSUBSCRIBE": "2",
}

_TERMINAL_EXEC_TYPES = {"CANCELED", "REJECTED", "EXPIRED"}


# ── Portfolio — in-memory episode state ───────────────────────────────────────

class Portfolio:
    """Tracks cash, open positions, and fill history for one episode."""

    def __init__(self, initial_cash: float = 15_000.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.locked_cash = 0.0
        self.positions: dict[str, dict] = {}   # {symbol: {qty, avg_price}}
        self.locked_positions: dict[str, int] = {} # {symbol: qty}
        self.active_orders: dict[str, dict] = {} # {order_id: {symbol, side, qty, price}}
        self.fills: list[dict] = []

    def reset(self, initial_cash: float | None = None) -> None:
        if initial_cash is not None:            # NOTE: "if initial_cash:" fails for 0.0
            self.initial_cash = initial_cash
        self.cash = self.initial_cash
        self.locked_cash = 0.0
        self.positions = {}
        self.locked_positions = {}
        self.active_orders = {}
        self.fills = []

    def place_order(self, order_id: str, symbol: str, side: str, qty: int, price: float) -> str | None:
        """Lock funds/positions. Returns error string if invalid, else None."""
        if side == "BUY":
            cost = qty * price
            if self.cash - self.locked_cash < cost:
                return f"Insufficient available funds: order costs {cost:.2f} but available is {(self.cash - self.locked_cash):.2f}"
            self.locked_cash += cost
        else:
            held = self.positions.get(symbol, {}).get("qty", 0)
            locked = self.locked_positions.get(symbol, 0)
            if held - locked < qty:
                return f"Insufficient available position: trying to sell {qty} {symbol} but only {held - locked} available"
            self.locked_positions[symbol] = locked + qty

        self.active_orders[order_id] = {"symbol": symbol, "side": side, "qty": qty, "price": price}
        return None

    def cancel_order(self, order_id: str) -> None:
        """Unlock remaining funds/positions for an order. Called via ExecutionReport."""
        order = self.active_orders.pop(order_id, None)
        if order:
            if order["side"] == "BUY":
                self.locked_cash -= order["qty"] * order["price"]
            else:
                self.locked_positions[order["symbol"]] -= order["qty"]
                if self.locked_positions[order["symbol"]] <= 0:
                    self.locked_positions.pop(order["symbol"], None)

    def apply_replacement(
        self,
        original_order_id: str,
        replacement_order_id: str,
        *,
        qty: float | int | None = None,
        price: float | None = None,
        symbol: str | None = None,
        side: str | None = None,
    ) -> None:
        order = self.active_orders.pop(original_order_id, None)
        if not order:
            return

        new_symbol = symbol or order["symbol"]
        new_side = side or order["side"]
        new_qty = float(qty) if qty is not None else float(order["qty"])
        if new_qty < 0:
            new_qty = 0
        new_price = float(price) if price is not None else float(order["price"])
        if new_price < 0:
            new_price = 0

        old_qty = float(order["qty"])
        old_price = float(order["price"])
        old_side = order["side"]
        old_symbol = order["symbol"]

        if old_side == "BUY":
            self.locked_cash += (new_qty * new_price) - (old_qty * old_price)
        else:
            self.locked_positions[old_symbol] = (
                self.locked_positions.get(old_symbol, 0.0) + (new_qty - old_qty)
            )
            if self.locked_positions[old_symbol] <= 0:
                self.locked_positions.pop(old_symbol, None)

        self.active_orders[replacement_order_id] = {
            "symbol": new_symbol,
            "side": new_side,
            "qty": new_qty,
            "price": new_price,
        }

    def record_fill(self, order_id: str, symbol: str, side: str, qty: int, price: float) -> None:
        # 1. Unlock reserving margin matching the fill qty
        order = self.active_orders.get(order_id)
        if order:
            if side == "BUY":
                self.locked_cash -= qty * order["price"]
            else:
                self.locked_positions[symbol] -= qty
            
            order["qty"] -= qty
            if order["qty"] <= 0:
                self.active_orders.pop(order_id)

        # 2. Apply actual execution to real balances
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
            "cash":           round(self.cash, 2),
            "available_cash": round(self.cash - self.locked_cash, 2),
            "net_profit":     round(self.net_profit(), 2),
            "positions":      {s: p for s, p in self.positions.items() if p["qty"] > 0},
            "open_orders":    len(self.active_orders),
            "total_fills":    len(self.fills),
        }


# ── QuantReplayClient — REST + FIX ───────────────────────────────────────────

class QuantReplayClient:
    """Communicates with QuantReplay via REST (admin/listings) and FIX (orders)."""

    def __init__(self):
        self._http = httpx.AsyncClient(base_url=REST_URL, timeout=10.0)
        self._sock: socket.socket | None = None
        self._parser = simplefix.FixParser()
        self._seq = 1
        self._order_events: list[dict] = []
        self._market_data_events: list[dict] = []
        self._security_status_events: list[dict] = []

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

    async def get_listing(self, symbol: str) -> dict:
        """Return full listing configuration for a symbol."""
        encoded = quote(symbol, safe="")
        r = await self._http.get(f"/api/listings/{encoded}")
        r.raise_for_status()
        return r.json()

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
        self._parser = simplefix.FixParser()
        self._order_events.clear()
        self._market_data_events.clear()
        self._security_status_events.clear()

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float | None,
        order_id: str | None = None,
        *,
        order_type: str = "LIMIT",
        time_in_force: str = "DAY",
    ) -> str:
        """Send NewOrderSingle (35=D). Returns ClOrdID for tracking."""
        order_type_value = self._normalize_order_type(order_type)
        tif_value = self._normalize_time_in_force(time_in_force)
        side_value = self._normalize_side(side)
        if order_type_value == "LIMIT" and (price is None or price <= 0):
            raise ValueError("LIMIT order requires positive price")
        if qty <= 0:
            raise ValueError("qty must be > 0")

        oid = order_id or uuid.uuid4().hex[:8]
        msg = self._build("D")
        msg.append_pair(11, oid)                 # ClOrdID
        msg.append_pair(21, "1")                 # HandlInst = AutoExec
        msg.append_pair(55, symbol)              # Symbol
        msg.append_pair(54, _SIDE_TO_FIX[side_value])       # Side
        msg.append_pair(38, str(qty))            # OrderQty
        msg.append_pair(40, _ORDER_TYPE_TO_FIX[order_type_value])
        if order_type_value == "LIMIT":
            msg.append_pair(44, f"{float(price):.4f}")
        msg.append_pair(60, self._now())         # TransactTime (required)
        msg.append_pair(59, _TIME_IN_FORCE_TO_FIX[tif_value])
        self._send(msg)
        logger.info(
            "NewOrderSingle: %s %s %d @ %s [%s] type=%s tif=%s",
            side_value,
            symbol,
            qty,
            f"{float(price):.4f}" if price is not None else "MKT",
            oid,
            order_type_value,
            tif_value,
        )
        return oid

    def cancel_order(self, order_id: str, symbol: str, side: str) -> None:
        """Send OrderCancelRequest (35=F).

        Note: qty NOT required per FIX RoE — only ClOrdID, Side, Symbol, TransactTime.
        """
        side_value = self._normalize_side(side)
        msg = self._build("F")
        msg.append_pair(11, uuid.uuid4().hex[:8])  # new ClOrdID for this cancel request
        msg.append_pair(41, order_id)               # OrigClOrdID
        msg.append_pair(55, symbol)
        msg.append_pair(54, _SIDE_TO_FIX[side_value])
        msg.append_pair(60, self._now())             # TransactTime (required)
        self._send(msg)

    def replace_order(
        self,
        *,
        orig_order_id: str,
        symbol: str,
        side: str,
        qty: int,
        price: float | None,
        order_id: str | None = None,
        order_type: str = "LIMIT",
        time_in_force: str = "DAY",
    ) -> str:
        """Send OrderCancelReplaceRequest (35=G). Returns replacement ClOrdID."""
        order_type_value = self._normalize_order_type(order_type)
        tif_value = self._normalize_time_in_force(time_in_force)
        side_value = self._normalize_side(side)
        if order_type_value == "LIMIT" and (price is None or price <= 0):
            raise ValueError("LIMIT replace requires positive price")
        if qty <= 0:
            raise ValueError("qty must be > 0")

        replacement_id = order_id or uuid.uuid4().hex[:8]
        msg = self._build("G")
        msg.append_pair(11, replacement_id)     # ClOrdID (new)
        msg.append_pair(41, orig_order_id)      # OrigClOrdID
        msg.append_pair(55, symbol)
        msg.append_pair(54, _SIDE_TO_FIX[side_value])
        msg.append_pair(38, str(qty))
        msg.append_pair(40, _ORDER_TYPE_TO_FIX[order_type_value])
        if order_type_value == "LIMIT":
            msg.append_pair(44, f"{float(price):.4f}")
        msg.append_pair(59, _TIME_IN_FORCE_TO_FIX[tif_value])
        msg.append_pair(60, self._now())
        self._send(msg)
        return replacement_id

    def market_data_snapshot(
        self,
        *,
        symbol: str,
        request_id: str | None = None,
        depth: str = "FULL",
        entry_types: list[str] | str | None = None,
    ) -> str:
        return self._send_market_data_request(
            symbol=symbol,
            request_type="SNAPSHOT",
            request_id=request_id,
            depth=depth,
            update_type="INCREMENTAL",
            entry_types=entry_types,
        )

    def market_data_subscribe(
        self,
        *,
        symbol: str,
        request_id: str | None = None,
        depth: str = "FULL",
        update_type: str = "INCREMENTAL",
        entry_types: list[str] | str | None = None,
    ) -> str:
        return self._send_market_data_request(
            symbol=symbol,
            request_type="SUBSCRIBE",
            request_id=request_id,
            depth=depth,
            update_type=update_type,
            entry_types=entry_types,
        )

    def market_data_unsubscribe(
        self,
        *,
        symbol: str,
        request_id: str,
        depth: str = "FULL",
        entry_types: list[str] | str | None = None,
    ) -> str:
        return self._send_market_data_request(
            symbol=symbol,
            request_type="UNSUBSCRIBE",
            request_id=request_id,
            depth=depth,
            update_type="INCREMENTAL",
            entry_types=entry_types,
        )

    def security_status_snapshot(self, *, symbol: str, request_id: str | None = None) -> str:
        return self._send_security_status_request(
            symbol=symbol,
            request_type="SNAPSHOT",
            request_id=request_id,
        )

    def security_status_subscribe(self, *, symbol: str, request_id: str | None = None) -> str:
        return self._send_security_status_request(
            symbol=symbol,
            request_type="SUBSCRIBE",
            request_id=request_id,
        )

    def security_status_unsubscribe(self, *, symbol: str, request_id: str) -> str:
        return self._send_security_status_request(
            symbol=symbol,
            request_type="UNSUBSCRIBE",
            request_id=request_id,
        )

    def poll_fills(self) -> list[dict]:
        """Read pending ExecutionReports. Returns fills and cancellations.

        ExecType values per FIX spec:
          0 = New, 4 = Canceled, 5 = Replaced, 8 = Rejected, C = Expired, F = Trade
        """
        fills: list[dict] = []
        self._drain_socket()

        remaining: list[dict] = []
        for event in self._order_events:
            if event.get("type") != "execution_report":
                remaining.append(event)
                continue

            exec_type = event.get("exec_type")
            if exec_type == "TRADE":
                qty = event.get("last_qty", 0)
                qty_int = int(qty) if isinstance(qty, (float, int)) else 0
                price = event.get("last_px", 0.0)
                price_float = float(price) if isinstance(price, (float, int)) else 0.0
                fills.append({
                    "order_id": event.get("order_id", ""),
                    "symbol": event.get("symbol", ""),
                    "side": event.get("side", ""),
                    "qty": qty_int,
                    "price": price_float,
                })
            elif exec_type in _TERMINAL_EXEC_TYPES:
                fills.append({
                    "order_id": event.get("order_id", ""),
                    "type": "CANCEL",
                })
            else:
                remaining.append(event)

        self._order_events = remaining
        return fills

    def poll_order_events(self) -> list[dict]:
        """Read detailed order lifecycle events from FIX (35=8, 35=9)."""
        self._drain_socket()
        events = self._order_events
        self._order_events = []
        return events

    def poll_market_data_events(self) -> list[dict]:
        """Read pending market data events from FIX (35=W/X/Y)."""
        self._drain_socket()
        events = self._market_data_events
        self._market_data_events = []
        return events

    def poll_security_status_events(self) -> list[dict]:
        """Read pending security status events from FIX (35=f/j)."""
        self._drain_socket()
        events = self._security_status_events
        self._security_status_events = []
        return events

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

    def _send_market_data_request(
        self,
        *,
        symbol: str,
        request_type: str,
        request_id: str | None,
        depth: str,
        update_type: str,
        entry_types: list[str] | str | None,
    ) -> str:
        req_type = request_type.strip().upper()
        if req_type not in _MD_SUBSCRIPTION_REQUEST_TO_FIX:
            raise ValueError(f"unsupported request_type: {request_type}")

        depth_code = self._normalize_market_depth(depth)
        normalized_entry_types = self._normalize_md_entry_types(entry_types)
        request_code = _MD_SUBSCRIPTION_REQUEST_TO_FIX[req_type]
        req_id = request_id or uuid.uuid4().hex[:8]

        msg = self._build("V")
        msg.append_pair(262, req_id)                 # MDReqID
        msg.append_pair(263, request_code)           # SubscriptionRequestType
        msg.append_pair(264, depth_code)             # MarketDepth
        if req_type == "SUBSCRIBE":
            update_code = self._normalize_md_update_type(update_type)
            msg.append_pair(265, update_code)        # MDUpdateType

        msg.append_pair(267, str(len(normalized_entry_types)))  # NoMDEntryTypes
        for md_type in normalized_entry_types:
            msg.append_pair(269, _MD_ENTRY_TYPE_TO_FIX[md_type])

        msg.append_pair(146, "1")                    # NoRelatedSym
        msg.append_pair(55, symbol)
        self._send(msg)
        return req_id

    def _send_security_status_request(
        self,
        *,
        symbol: str,
        request_type: str,
        request_id: str | None,
    ) -> str:
        req_type = request_type.strip().upper()
        if req_type not in _SECURITY_SUBSCRIPTION_REQUEST_TO_FIX:
            raise ValueError(f"unsupported request_type: {request_type}")

        req_id = request_id or uuid.uuid4().hex[:8]
        msg = self._build("e")
        msg.append_pair(324, req_id)                                   # SecurityStatusReqID
        msg.append_pair(55, symbol)
        msg.append_pair(263, _SECURITY_SUBSCRIPTION_REQUEST_TO_FIX[req_type])  # SubscriptionRequestType
        self._send(msg)
        return req_id

    def _drain_socket(self) -> None:
        if not self._sock:
            return

        self._sock.setblocking(False)
        try:
            while True:
                try:
                    data = self._sock.recv(4096)
                except BlockingIOError:
                    break
                except socket.timeout:
                    break

                if not data:
                    break

                self._parser.append_buffer(data)
                while msg := self._parser.get_message():
                    self._route_incoming_message(msg)
        except OSError:
            pass
        finally:
            self._sock.setblocking(True)
            self._sock.settimeout(0.5)

    def _route_incoming_message(self, msg: simplefix.FixMessage) -> None:
        msg_type = self._decode_bytes(msg.get(35))
        if not msg_type:
            return

        if msg_type == "8":
            self._order_events.append(self._parse_execution_report(msg))
        elif msg_type == "9":
            self._order_events.append(self._parse_cancel_reject(msg))
        elif msg_type in ("W", "X"):
            self._market_data_events.append(self._parse_market_data_update(msg, msg_type))
        elif msg_type == "Y":
            self._market_data_events.append(self._parse_market_data_reject(msg))
        elif msg_type == "f":
            self._security_status_events.append(self._parse_security_status(msg))
        elif msg_type == "j":
            self._security_status_events.append(self._parse_business_reject(msg))

    def _parse_execution_report(self, msg: simplefix.FixMessage) -> dict:
        pairs = self._decode_pairs(msg)
        cl_ord_id = self._first_tag(pairs, "11")
        orig_cl_ord_id = self._first_tag(pairs, "41")
        venue_order_id = self._first_tag(pairs, "37")
        exec_type_code = self._first_tag(pairs, "150")
        ord_status_code = self._first_tag(pairs, "39")

        event = {
            "type": "execution_report",
            "msg_type": "8",
            "exec_type_code": exec_type_code,
            "exec_type": _FIX_EXEC_TYPE_TO_TEXT.get(exec_type_code, exec_type_code),
            "ord_status_code": ord_status_code,
            "ord_status": _FIX_ORD_STATUS_TO_TEXT.get(ord_status_code, ord_status_code),
            "cl_ord_id": cl_ord_id,
            "orig_cl_ord_id": orig_cl_ord_id,
            "venue_order_id": venue_order_id,
            "order_id": cl_ord_id or orig_cl_ord_id or venue_order_id or "",
            "exec_id": self._first_tag(pairs, "17"),
            "symbol": self._first_tag(pairs, "55"),
            "side": _FIX_SIDE_TO_TEXT.get(self._first_tag(pairs, "54"), self._first_tag(pairs, "54")),
            "order_type": self._first_tag(pairs, "40"),
            "time_in_force": self._first_tag(pairs, "59"),
            "order_price": self._to_float(self._first_tag(pairs, "44")),
            "order_qty": self._to_float(self._first_tag(pairs, "38")),
            "leaves_qty": self._to_float(self._first_tag(pairs, "151")),
            "cum_qty": self._to_float(self._first_tag(pairs, "14")),
            "last_qty": self._to_float(self._first_tag(pairs, "32")),
            "last_px": self._to_float(self._first_tag(pairs, "31")),
            "text": self._first_tag(pairs, "58"),
        }
        return event

    def _parse_cancel_reject(self, msg: simplefix.FixMessage) -> dict:
        pairs = self._decode_pairs(msg)
        response_to = self._first_tag(pairs, "434")
        response_text = {
            "1": "CANCEL_REQUEST",
            "2": "REPLACE_REQUEST",
        }.get(response_to, response_to)
        return {
            "type": "order_cancel_reject",
            "msg_type": "9",
            "cl_ord_id": self._first_tag(pairs, "11"),
            "orig_cl_ord_id": self._first_tag(pairs, "41"),
            "venue_order_id": self._first_tag(pairs, "37"),
            "order_id": self._first_tag(pairs, "11") or self._first_tag(pairs, "41") or "",
            "ord_status_code": self._first_tag(pairs, "39"),
            "ord_status": _FIX_ORD_STATUS_TO_TEXT.get(self._first_tag(pairs, "39"), self._first_tag(pairs, "39")),
            "response_to_code": response_to,
            "response_to": response_text,
            "text": self._first_tag(pairs, "58"),
        }

    def _parse_market_data_update(self, msg: simplefix.FixMessage, msg_type: str) -> dict:
        pairs = self._decode_pairs(msg)
        event = {
            "type": "market_data_snapshot" if msg_type == "W" else "market_data_update",
            "msg_type": msg_type,
            "request_id": self._first_tag(pairs, "262"),
            "symbol": self._first_tag(pairs, "55"),
            "last_update_time": self._first_tag(pairs, "779"),
            "entries": self._parse_md_entries(pairs, msg_type=msg_type),
        }
        return event

    def _parse_market_data_reject(self, msg: simplefix.FixMessage) -> dict:
        pairs = self._decode_pairs(msg)
        reason_code = self._first_tag(pairs, "281")
        return {
            "type": "market_data_reject",
            "msg_type": "Y",
            "request_id": self._first_tag(pairs, "262"),
            "reason_code": reason_code,
            "reason": _FIX_MD_REJECT_REASON_TO_TEXT.get(reason_code, reason_code),
            "text": self._first_tag(pairs, "58"),
        }

    def _parse_security_status(self, msg: simplefix.FixMessage) -> dict:
        pairs = self._decode_pairs(msg)
        phase_code = self._first_tag(pairs, "625")
        status_code = self._first_tag(pairs, "326")
        return {
            "type": "security_status",
            "msg_type": "f",
            "request_id": self._first_tag(pairs, "324"),
            "symbol": self._first_tag(pairs, "55"),
            "trading_session_id": self._first_tag(pairs, "336"),
            "trading_phase_code": phase_code,
            "trading_phase": _FIX_TRADING_PHASE_TO_TEXT.get(phase_code, phase_code),
            "trading_status_code": status_code,
            "trading_status": _FIX_SECURITY_STATUS_TO_TEXT.get(status_code, status_code),
        }

    def _parse_business_reject(self, msg: simplefix.FixMessage) -> dict:
        pairs = self._decode_pairs(msg)
        reason_code = self._first_tag(pairs, "380")
        reason = {
            "0": "OTHER",
            "1": "UNKNOWN_ID",
            "2": "UNKNOWN_SECURITY",
        }.get(reason_code, reason_code)
        return {
            "type": "business_reject",
            "msg_type": "j",
            "ref_msg_type": self._first_tag(pairs, "372"),
            "ref_seq_num": self._first_tag(pairs, "45"),
            "ref_id": self._first_tag(pairs, "379"),
            "reason_code": reason_code,
            "reason": reason,
            "text": self._first_tag(pairs, "58"),
        }

    def _parse_md_entries(self, pairs: list[tuple[str, str]], *, msg_type: str) -> list[dict]:
        boundary_tag = "269" if msg_type == "W" else "279"
        entries: list[dict] = []
        current: dict | None = None

        for tag, value in pairs:
            if tag == boundary_tag:
                if current is not None:
                    entries.append(current)
                current = {}
                if msg_type == "W":
                    current["entry_type_code"] = value
                    current["entry_type"] = _FIX_MD_ENTRY_TYPE_TO_TEXT.get(value, value)
                else:
                    current["action_code"] = value
                    current["action"] = _FIX_MD_UPDATE_ACTION_TO_TEXT.get(value, value)
                continue

            if current is None:
                continue

            if tag == "269":
                current["entry_type_code"] = value
                current["entry_type"] = _FIX_MD_ENTRY_TYPE_TO_TEXT.get(value, value)
            elif tag == "278":
                current["entry_id"] = value
            elif tag == "270":
                current["price"] = self._to_float(value)
            elif tag == "271":
                current["size"] = self._to_float(value)
            elif tag == "272":
                current["trade_date"] = value
            elif tag == "273":
                current["trade_time"] = value
            elif tag == "288":
                current["buyer_id"] = value
            elif tag == "289":
                current["seller_id"] = value
            elif tag == "2446":
                current["aggressor_side_code"] = value
                current["aggressor_side"] = _FIX_SIDE_TO_TEXT.get(value, value)
            elif tag == "326":
                current["trading_status_code"] = value
                current["trading_status"] = _FIX_SECURITY_STATUS_TO_TEXT.get(value, value)
            elif tag == "625":
                current["trading_phase_code"] = value
                current["trading_phase"] = _FIX_TRADING_PHASE_TO_TEXT.get(value, value)
            elif tag == "336":
                current["trading_session_id"] = value
            elif tag == "277":
                current["trade_condition"] = value

        if current is not None:
            entries.append(current)
        return entries

    def _normalize_order_type(self, order_type: str) -> str:
        key = order_type.strip().upper()
        if key not in _ORDER_TYPE_TO_FIX:
            raise ValueError(f"unsupported order_type: {order_type}")
        return key

    def _normalize_time_in_force(self, time_in_force: str) -> str:
        key = time_in_force.strip().upper()
        if key not in _TIME_IN_FORCE_TO_FIX:
            raise ValueError(f"unsupported time_in_force: {time_in_force}")
        return key

    def _normalize_side(self, side: str) -> str:
        key = side.strip().upper().replace("-", "_")
        if key not in _SIDE_TO_FIX:
            raise ValueError(f"unsupported side: {side}")
        return key

    def _normalize_market_depth(self, depth: str) -> str:
        key = depth.strip().upper()
        if key not in _MD_DEPTH_TO_FIX:
            raise ValueError(f"unsupported depth: {depth}")
        return _MD_DEPTH_TO_FIX[key]

    def _normalize_md_update_type(self, update_type: str) -> str:
        key = update_type.strip().upper()
        if key not in _MD_UPDATE_TYPE_TO_FIX:
            raise ValueError(f"unsupported update_type: {update_type}")
        return _MD_UPDATE_TYPE_TO_FIX[key]

    def _normalize_md_entry_types(self, entry_types: list[str] | str | None) -> list[str]:
        if entry_types is None:
            values = ["BID", "OFFER", "TRADE"]
        elif isinstance(entry_types, str):
            values = [token.strip().upper() for token in entry_types.split(",") if token.strip()]
        else:
            values = [str(token).strip().upper() for token in entry_types if str(token).strip()]

        if not values:
            raise ValueError("entry_types must include at least one value")

        deduped: list[str] = []
        for value in values:
            if value not in _MD_ENTRY_TYPE_TO_FIX:
                raise ValueError(f"unsupported market data entry type: {value}")
            if value not in deduped:
                deduped.append(value)
        return deduped

    @staticmethod
    def _decode_bytes(value: bytes | None) -> str:
        if value is None:
            return ""
        return value.decode(errors="ignore")

    @staticmethod
    def _decode_pairs(msg: simplefix.FixMessage) -> list[tuple[str, str]]:
        decoded: list[tuple[str, str]] = []
        for tag, value in msg.pairs:
            decoded.append((tag.decode(errors="ignore"), value.decode(errors="ignore")))
        return decoded

    @staticmethod
    def _first_tag(pairs: list[tuple[str, str]], tag: str) -> str:
        for key, value in pairs:
            if key == tag:
                return value
        return ""

    @staticmethod
    def _to_float(value: str) -> float | None:
        if value == "":
            return None
        try:
            return float(value)
        except ValueError:
            return None

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
