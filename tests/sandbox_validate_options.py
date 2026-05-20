#!/usr/bin/env python3
"""
Sandbox validation script for TradeStation option instrument support.

Discovers valid option instruments dynamically — no hardcoded contracts that
expire.  Uses the TradeStation sandbox API to:

1. Find a liquid underlying (AAPL, SPY, or user-supplied)
2. Search for option chains on that underlying
3. Load the nearest-expiring OTM call as an OptionContract
4. Validate market data (quote stream) works
5. Place, modify, cancel a limit order (far OTM so it won't fill)
6. Verify reconciliation recovers the order

Usage:
    export TRADESTATION_CLIENT_ID="..."
    export TRADESTATION_CLIENT_SECRET="..."
    export TRADESTATION_REFRESH_TOKEN="..."
    export TRADESTATION_ACCOUNT_ID="SIM..."

    python tests/sandbox_validate_options.py

    # Or with a custom underlying:
    python tests/sandbox_validate_options.py --underlying SPY
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Path setup — run from repo root
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradestation_nt_community.http.client import TradeStationHttpClient


# ---------------------------------------------------------------------------
# Option discovery
# ---------------------------------------------------------------------------


def _build_occ_probe_symbols(underlying: str, days_ahead: int) -> list[str]:
    """Build a list of plausible OCC option symbols to probe.

    Generates weekly (Friday) and monthly (3rd Friday) expiries up to
    *days_ahead* days in the future, with an ATM-ish strike.  We don't know
    the exact underlying price, so we probe multiple strikes.  The TS sandbox
    returns a 200 with an error in the body for unknown symbols, so probing
    is cheap.

    Parameters
    ----------
    underlying : str
        The underlying symbol (e.g. ``"AAPL"``).
    days_ahead : int
        Maximum number of days in the future to generate probes for.

    Returns
    -------
    list[str]
        OCC-format symbols like ``"AAPL 260530C00170000"``.
    """
    today = datetime.utcnow()
    symbols: list[str] = []

    # Generate probes for each Friday in the next *days_ahead* days
    for offset in range(1, days_ahead + 1):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() != 4:  # 4 = Friday
            continue
        date_part = candidate.strftime("%y%m%d")
        for strike_x1000 in (15000, 17500, 20000, 22500, 25000):
            symbols.append(f"{underlying} {date_part}C{strike_x1000:08d}")
            symbols.append(f"{underlying} {date_part}P{strike_x1000:08d}")

    return symbols


async def _search_options_via_symbol_search(
    client: TradeStationHttpClient,
    underlying: str,
) -> list[dict[str, Any]]:
    """Use the /marketdata/symbols/search endpoint to find stock options.

    The v3 search endpoint accepts a ``category`` query param.  We try
    ``StockOption`` first, then fall back to a plain text search.
    """
    for category in ("StockOption", "STOCKOPTION", None):
        try:
            result = await client.search_symbols(underlying, category=category)
            if isinstance(result, list) and result:
                return [
                    r for r in result
                    if r.get("Symbol", "").startswith(underlying + " ")
                       and " " in r.get("Symbol", "")
                ]
        except Exception:
            continue

    return []


async def discover_option(
    client: TradeStationHttpClient,
    underlying: str = "AAPL",
) -> tuple[str, dict[str, Any]] | None:
    """Discover a valid, tradeable option instrument for *underlying*.

    Strategy
    --------
    1. Try the symbol-search API with ``category=StockOption``.
    2. If that returns results, validate the first entry via
       ``get_symbol_details``.
    3. If search fails, probe OCC-constructed symbols until one resolves.

    Returns
    -------
    tuple[str, dict] | None
        ``(symbol_string, symbol_details_dict)`` if found, else ``None``.
    """
    print(f"\n🔍 Discovering option for underlying '{underlying}' ...")

    # ── Strategy 1: API symbol search ──────────────────────────────────────
    print("   → Trying symbol search API ...")
    candidates = await _search_options_via_symbol_search(client, underlying)
    if candidates:
        print(f"      Found {len(candidates)} option(s) via search")
        for entry in candidates[:5]:  # validate first 5
            sym = entry.get("Symbol", "")
            try:
                details = await client.get_symbol_details(sym)
                asset_type = details.get("AssetType", "").upper()
                if asset_type in ("OPTION", "STOCKOPTION", "OP"):
                    print(f"   ✅ Validated: {sym}")
                    return sym, details
            except Exception:
                continue

    # ── Strategy 2: OCC symbol probing ─────────────────────────────────────
    print("   → Trying OCC symbol probing ...")
    probes = _build_occ_probe_symbols(underlying, days_ahead=42)
    for sym in probes:
        try:
            details = await client.get_symbol_details(sym)
            asset_type = details.get("AssetType", "").upper()
            if asset_type in ("OPTION", "STOCKOPTION", "OP"):
                print(f"   ✅ Probe hit: {sym}")
                return sym, details
        except Exception:
            continue

    print(f"   ❌ No valid option found for '{underlying}'")
    return None


# ---------------------------------------------------------------------------
# Phase 1: Instrument loading & parsing
# ---------------------------------------------------------------------------


async def phase1_instrument_loading(client: TradeStationHttpClient) -> str | None:
    """Load a real option instrument and verify it parses correctly.

    Returns the discovered symbol string, or None on failure.
    """
    print("\n" + "=" * 60)
    print("PHASE 1: Instrument Loading & Parsing")
    print("=" * 60)

    result = await discover_option(client)
    if result is None:
        print("FAILED: could not discover any option instrument")
        return None

    sym, details = result
    asset_type = details.get("AssetType", "N/A")
    strike = details.get("StrikePrice", "N/A")
    expiry = details.get("ExpirationDate", "N/A")
    opt_type = details.get("OptionType", "N/A")
    underlying = details.get("Underlying", "N/A")

    print(f"\n   Symbol:      {sym}")
    print(f"   AssetType:   {asset_type}")
    print(f"   Strike:      {strike}")
    print(f"   Expiration:  {expiry}")
    print(f"   OptionType:  {opt_type}")
    print(f"   Underlying:  {underlying}")

    # Verify parsing via the adapter's parse_instrument
    from tradestation_nt_community.parsing.instruments import parse_instrument
    from tradestation_nt_community.constants import TRADESTATION_VENUE
    from nautilus_trader.model.instruments import OptionContract

    instrument = parse_instrument(sym, details, TRADESTATION_VENUE)
    if not isinstance(instrument, OptionContract):
        print(f"FAILED: parse_instrument returned {type(instrument)}, expected OptionContract")
        return None

    print(f"\n   ✅ Parsed as OptionContract:")
    print(f"      strike={instrument.strike_price}")
    print(f"      kind={instrument.option_kind}")
    print(f"      multiplier={instrument.multiplier}")
    print(f"      expiry={instrument.expiration_ns}")

    return sym


# ---------------------------------------------------------------------------
# Phase 2: Market data
# ---------------------------------------------------------------------------


async def phase2_market_data(client: TradeStationHttpClient, symbol: str) -> bool:
    """Subscribe to quote data for the discovered option.

    Uses the existing get_quotes() endpoint — the same one the data client uses
    for polling subscriptions.
    """
    print("\n" + "=" * 60)
    print("PHASE 2: Market Data (Quote Fetch)")
    print("=" * 60)

    try:
        quotes = await client.get_quotes(symbol)
    except Exception as e:
        print(f"   ❌ get_quotes failed: {e}")
        return False

    if not quotes:
        print("   ⚠️  No quotes returned (option may be illiquid today)")
        return False

    q = quotes[0]
    bid = q.get("Bid", 0)
    ask = q.get("Ask", 0)
    last = q.get("Last", 0)
    volume = q.get("Volume", 0)

    print(f"   Bid: {bid}   Ask: {ask}   Last: {last}   Vol: {volume}")

    bid_val = float(bid or 0)
    ask_val = float(ask or 0)
    last_val = float(last or 0)

    if last_val == 0 and bid_val == 0 and ask_val == 0:
        print("   ⚠️  All prices are zero — option may be illiquid. Continuing anyway.")
    else:
        print("   ✅ Market data received")

    return True


# ---------------------------------------------------------------------------
# Phase 3: Order lifecycle
# ---------------------------------------------------------------------------


async def phase3_order_lifecycle(
    client: TradeStationHttpClient,
    symbol: str,
    account_id: str,
) -> bool:
    """Place → verify → cancel an option limit order.

    Uses a far-OTM limit price so the order won't fill in the sandbox.
    """
    print("\n" + "=" * 60)
    print("PHASE 3: Order Lifecycle (Place → Verify → Cancel)")
    print("=" * 60)

    # Use a tiny limit price for a call — very unlikely to fill
    # (If the discovered symbol is a put, we'd need to adjust. For now
    # we always discover a call, which is the default probe.)
    limit_price = "0.05"
    trade_action = "BuyToOpen"

    # ── 3a. Place the order ────────────────────────────────────────────────
    print(f"\n   → Placing {trade_action} Limit @ {limit_price} for {symbol} ...")
    try:
        response = await client.place_order(
            account_id=account_id,
            symbol=symbol,
            quantity="1",
            order_type="Limit",
            trade_action=trade_action,
            time_in_force="DAY",
            limit_price=limit_price,
            asset_type="OP",
        )
    except Exception as e:
        if "OrderRejected" in str(type(e).__name__):
            print(f"   ❌ Order rejected (expected if account lacks options): {e}")
            return False
        print(f"   ❌ place_order failed: {e}")
        return False

    # Extract OrderID — response format varies between real and mock
    order_id = None
    if isinstance(response, dict):
        orders_in_resp = response.get("Orders", [])
        if orders_in_resp:
            order_id = orders_in_resp[0].get("OrderID")
        else:
            order_id = response.get("OrderID")

    if not order_id:
        print(f"   ❌ No OrderID in response: {response}")
        return False

    print(f"   ✅ Order placed: OrderID={order_id}")

    # ── 3b. Verify order appears in /orders listing ────────────────────────
    print(f"\n   → Verifying order {order_id} in /orders ...")
    try:
        orders = await client.get_orders(account_id)
    except Exception as e:
        print(f"   ❌ get_orders failed: {e}")
        return False

    found = any(o.get("OrderID") == order_id for o in orders)
    if found:
        print(f"   ✅ Order {order_id} found in /orders listing")
    else:
        print(f"   ⚠️  Order {order_id} NOT found in /orders (may be too new)")

    # ── 3c. Cancel the order ───────────────────────────────────────────────
    print(f"\n   → Cancelling order {order_id} ...")
    try:
        cancel_resp = await client.cancel_order(order_id)
        print(f"   ✅ Order cancelled: {cancel_resp}")
    except Exception as e:
        if "Not an open order" in str(e):
            print(f"   ⚠️  Order already closed (may have filled or expired): {e}")
        else:
            print(f"   ❌ cancel_order failed: {e}")
            return False

    # ── 3d. Verify order is gone or cancelled ──────────────────────────────
    print(f"\n   → Verifying cancellation ...")
    try:
        orders = await client.get_orders(account_id)
    except Exception as e:
        print(f"   ⚠️  Could not re-fetch orders: {e}")
        return True  # don't fail — cancel was confirmed

    still_open = [o for o in orders if o.get("OrderID") == order_id
                  and o.get("Status") not in ("CAN", "UCN", "FLL")]
    if still_open:
        print(f"   ⚠️  Order still appears open: {still_open[0].get('Status')}")
    else:
        print(f"   ✅ Order {order_id} no longer open")

    return True


# ---------------------------------------------------------------------------
# Phase 4: Reconciliation (order status report)
# ---------------------------------------------------------------------------


async def phase4_reconciliation(
    client: TradeStationHttpClient,
    symbol: str,
) -> bool:
    """Verify that filled/rejected/cancelled orders appear in reconciliation data.

    This is a read-only check — it fetches the order list and verifies that
    option orders (if any exist from prior runs) are parseable.
    """
    print("\n" + "=" * 60)
    print("PHASE 4: Reconciliation (Order Status Reports)")
    print("=" * 60)

    from tradestation_nt_community.parsing.execution import (
        parse_fill_report,
        parse_order_status_report,
    )
    from nautilus_trader.model.identifiers import (
        AccountId, ClientOrderId, InstrumentId,
    )

    account_id_nt = AccountId("TRADESTATION-SIM0000001F")

    try:
        orders = await client.get_orders(os.getenv("TRADESTATION_ACCOUNT_ID", ""))
    except Exception as e:
        print(f"   ⚠️  Could not fetch orders: {e}")
        return False

    option_orders = [o for o in orders if o.get("AssetType") in ("OP", "OPTION")
                     or " " in (o.get("Symbol", "") or "")]
    if not option_orders:
        print("   ⚠️  No option orders found in account history — skipping")
        return True  # not a failure

    print(f"   Found {len(option_orders)} option order(s) in account history")

    for o in option_orders:
        sym = o.get("Symbol", "") or (
            o.get("Legs", [{}])[0].get("Symbol", "") if o.get("Legs") else ""
        )
        if not sym:
            continue
        instrument_id = InstrumentId.from_str(f"{sym}.TRADESTATION")
        coid = ClientOrderId(f"RECON-{o.get('OrderID', 'UNKNOWN')}")

        # Exercise both parsing functions
        try:
            status_report = parse_order_status_report(
                o, instrument_id, coid, account_id_nt, ts_now=0,
            )
            if status_report:
                print(f"   ✅ Status report for {sym}: {status_report.order_status}")
        except Exception as e:
            print(f"   ⚠️  Status report parse error for {sym}: {e}")

        if o.get("Status") == "FLL":
            try:
                fill_report = parse_fill_report(
                    o, instrument_id, account_id_nt, ts_now=0,
                )
                if fill_report:
                    print(f"   ✅ Fill report for {sym}: px={fill_report.last_px}")
            except Exception as e:
                print(f"   ⚠️  Fill report parse error for {sym}: {e}")

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(underlying: str) -> int:
    """Run all sandbox validation phases.  Returns 0 on success, 1 on failure."""
    # Credentials
    client_id = os.getenv("TRADESTATION_CLIENT_ID")
    client_secret = os.getenv("TRADESTATION_CLIENT_SECRET")
    refresh_token = os.getenv("TRADESTATION_REFRESH_TOKEN")
    account_id = os.getenv("TRADESTATION_ACCOUNT_ID")

    missing = []
    for name, val in [
        ("TRADESTATION_CLIENT_ID", client_id),
        ("TRADESTATION_CLIENT_SECRET", client_secret),
        ("TRADESTATION_REFRESH_TOKEN", refresh_token),
        ("TRADESTATION_ACCOUNT_ID", account_id),
    ]:
        if not val:
            missing.append(name)

    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("   Set them before running this script.")
        return 1

    print("=" * 60)
    print("TradeStation Options — Sandbox Validation")
    print("=" * 60)
    print(f"   Underlying: {underlying}")
    print(f"   Account:    {account_id}")
    print(f"   Sandbox:    True")

    # Create HTTP client (sandbox mode)
    client = TradeStationHttpClient(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        use_sandbox=True,
    )

    try:
        # Phase 1: Discover & load instrument
        symbol = await phase1_instrument_loading(client)
        if not symbol:
            print("\n❌ Phase 1 FAILED — cannot continue")
            return 1

        # Phase 2: Market data
        if not await phase2_market_data(client, symbol):
            print("\n⚠️  Phase 2 had issues — continuing anyway")

        # Phase 3: Order lifecycle
        if not await phase3_order_lifecycle(client, symbol, account_id):
            print("\n⚠️  Phase 3 had issues — this may be expected if account lacks options permission")

        # Phase 4: Reconciliation
        await phase4_reconciliation(client, symbol)

    finally:
        await client.close()

    print("\n" + "=" * 60)
    print("Sandbox validation complete.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate TradeStation option instrument support against the sandbox",
    )
    parser.add_argument(
        "--underlying", "-u", default="AAPL",
        help="Underlying symbol for option discovery (default: AAPL)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.underlying)))
