# TODO — Options Support

## Status

Source, tests, and sandbox validation are all runnable in this environment
(`.venv` has `nautilus_trader==1.227.0` installed). 392/392 unit tests pass.

`tests/sandbox_validate_options.py` has been run live against the TradeStation
sandbox multiple times, both with the market closed (2026-09-06) and — via the
scheduled cron job — during market hours (2026-09-08). Every run logs to both
the console and a timestamped file under `logs/` (git-ignored) so an
unattended/scheduled run can be diagnosed after the fact without anyone
watching it live. A weekday cron job keeps re-running it at ~11:30 ET; see
`README.md`'s "Scheduled Sandbox Validation" section for how to view/edit/
cancel it.

---

## What's currently supported

**Instrument types** — both discovered the same way (`get_option_expirations`
→ `get_option_strikes` → `get_symbol_details`), OCC-style symbol format
(e.g. `AAPL 260909C310`, `$SPX.X 260918C7085`):
- **Equity (stock) options** — parsed as `OptionContract` with `asset_class=EQUITY`
- **Index options** — underlying prefixed with `$` (e.g. `$SPX.X`) auto-detected
  and parsed as `OptionContract` with `asset_class=INDEX`
- Both **single-leg only** — `get_option_strikes()` explicitly discards the
  second leg of any TS strike group (`legs[0]` only in `http/client.py`), so
  spreads/multi-leg combos aren't reachable through this adapter's discovery
  helper even though TradeStation's API hints at supporting them (`Strikes`
  comes back as leg-groups)
- Multiplier: 100/contract; strike/expiry/kind all parse correctly

**Market data**: REST quotes and SSE quote streaming both confirmed working
live, market open or closed. Historical bars (`get_bars`) — never actually
called against an option symbol anywhere, in tests or examples; the endpoint
is symbol-agnostic so it should work, but there's zero verification either way.

**Execution**: place / modify (cancel-replace) / cancel all confirmed live
against a real order book (2026-09-08 cron run). But only **`BuyToOpen`/
`SellToOpen`** — opening positions only; see Gap 3c. OCO/bracket order groups
(`place_order_group`) exist generically and are used by the futures/equities
paths, but have never been sandbox-tested with option legs specifically —
only mock-tested.

**Reconciliation**: status parsing is solid, including `OUT` (fixed
2026-09-09 — see Gap 3b-2). Fill-report parsing (`parse_fill_report`) exists
in code but has never run against a real fill — see "Untested workflows" below.

---

## Sandbox validation — what's been confirmed live

- [x] **Phase 1: Instrument loading** — option discovered and parsed as `OptionContract`
- [x] **Phase 2: Market data** — quotes received for the option symbol
- [x] **Phase 2b: SSE quote streaming** — connects and delivers quote events for an
      option symbol, market open or closed
- [x] **Phase 3: Order lifecycle (place → verify → modify → cancel)** —
      confirmed against a *closed* market (2026-09-06, correctly rejected as
      "markets are closed", not a code bug) **and** against a real, open
      order book (2026-09-08 cron run: placed `OrderID=970410836`, verified,
      modified limit price 0.05→0.06, cancelled — all succeeded)
- [x] **Phase 3f: Deliberate rejection** — an intentionally invalid order
      (quantity=0) is rejected by TradeStation (HTTP 400, not the 200+FAILED
      body-error shape `OrderRejectedException` targets — logged as a WARN
      noting the exception type differs from what was expected)
- [x] **Phase 4: Reconciliation** — order listing fetch and report parsing work
- [x] **Phase 5/6: Index + index option loading** — `$SPX.X` and a discovered
      index option both parse correctly (INDEX asset class)

Run it yourself:
```bash
cd /home/ubuntu/workarea/tradestation-nt-community
.venv/bin/python tests/sandbox_validate_options.py
# Or with a different underlying:
.venv/bin/python tests/sandbox_validate_options.py --underlying SPY --index '$SPX.X'
```
Credentials are already populated in `.env` — no setup needed.

---

## Untested workflows (discussed 2026-09-09, not yet started)

**Biggest gap: the actual NautilusTrader integration layer has never been
exercised for options.** Every sandbox run so far talks directly to
`TradeStationHttpClient`/`TradeStationStreamClient` — it never instantiates
`TradeStationExecutionClient`, `TradeStationDataClient`, or a real
`TradingNode`. So the layer that actually matters to a strategy — turning TS
events into `OrderFilled`/`OrderCanceled`, publishing `Bar`/`QuoteTick` on the
message bus, driving `_check_order_statuses()` and the SSE order-stream
handler — has only ever seen options via mocked unit-test fixtures, never
live data. We've proven the HTTP/SSE plumbing works; we haven't proven the
adapter *as NautilusTrader actually uses it* works.

Roughly in order of how much each matters:

1. **A real fill.** Every test order so far has used a deliberately-unfillable
   far-OTM limit price, so `generate_order_filled` / `parse_fill_report`
   against a genuine `FLL` status has never fired for an option.
2. **Closing a position** (`BuyToClose`/`SellToClose`) — doesn't exist yet
   (Gap 3c below), so untested by definition.
3. **Multi-leg spreads** — unsupported (see "What's currently supported" above).
4. **OCO/bracket groups with option legs** — code exists, sandbox-untested.
5. **Partial fills (FLP)** — adapter-wide known limitation (options especially
   prone to partials); see README's "Known Constraints".
6. **CASH account type actually trading options** — the config wiring is
   unit-tested (Gap 3a), never run against a real CASH sandbox account.
7. **Assignment/exercise** — no code for this exists at all; equity options
   can be assigned early and there's no handling for that event.
8. **Long-lived streaming** — the SSE check in Phase 2b is a ~12-second
   one-shot per run; multi-hour streaming, reconnect-after-drop, and
   token-refresh-mid-stream are only proven for non-option symbols via mocks,
   never live for options.
9. **Futures/equities regression** — not options-specific, but still
   outstanding: the URL-encoding fix (SECURITY_REVIEW.md #5) touches every
   symbol type through the shared HTTP/streaming clients, but has only been
   spot-checked against options and `$SPX.X` so far — never against a plain
   futures contract or equity ticker.

Best next step discussed: spin up a real (short-lived) `TradingNode` against
the sandbox with a trivial strategy that places a *marketable* option order
and watches for `OrderFilled` — that would close gaps #1 and the "integration
layer" gap at once.

---

## Gaps

### 3a. Account type config test — DONE

`tests/test_factories.py::TestAccountTypeConfigFlowThrough` verifies
`TradeStationExecClientConfig(account_type="CASH")` flows through the factory
into `AccountType.CASH`, that the default is `AccountType.MARGIN`, and that an
unrecognised string falls back to `MARGIN` rather than raising.

### 3b. SSE streaming with option symbols — DONE

Confirmed live in Phase 2b above: `stream_quotes()` connects and delivers
option quote events, market open or closed.

### 3b-2. `OUT` order status — DONE (2026-09-09)

The 2026-09-08 live run surfaced a false "still appears open" warning after a
successful cancel: TradeStation returned status `OUT`, which
`parsing/execution.py`'s `_TS_STATUS_TO_NT` map and `execution.py`'s own
live-order-monitoring loops already treat as `CANCELED` — but
`sandbox_validate_options.py`'s own hardcoded "still open" check
(`("CAN", "UCN", "FLL")`) didn't know about it. Fixed by aligning the script's
check with `execution.py`'s canonical terminal-status set
(`CAN`/`UCN`/`OUT`/`EXP`/`DON`/`FLL`), and backfilled the documentation-only
`TradeStationOrderStatus` enum in `common/enums.py` (which also lacked `OUT`
and is otherwise unreferenced anywhere in the codebase).

### 3c. `BuyToClose` / `SellToClose` support — still open

Current mapping in `execution.py` (`_submit_order`) is simple:
```
BUY  → BuyToOpen
SELL → SellToOpen
```
If a strategy needs to close an existing option position, add an optional
`trade_action_override` kwarg to `_submit_order` / `_convert_order_to_ts_format`.

### 3d. Options example script — still open

Create `examples/tradestation_options_example.py` based on the existing
`tradestation_example.py`, using a dynamically-discovered option (same
discovery approach as `sandbox_validate_options.py`). This would also be a
natural home for the real-`TradingNode`-with-a-fill test discussed above.

---

## Pre-release checklist

- [x] All unit tests pass (`pytest tests/ -q`) — 392 passing
- [x] Sandbox validation passes for all reference-data/parsing/streaming
      phases; order place/modify/cancel confirmed against a live order book
      (2026-09-08)
- [ ] Regression: existing futures + equities still work (run existing
      examples) — not yet done; see "Untested workflows" #9 above
- [ ] Real fill + NautilusTrader integration layer exercised for options —
      see "Untested workflows" above (new, added 2026-09-09)
- [x] README / CLAUDE.md / docs updated
- [ ] CHANGELOG entry (if applicable)
- [ ] Tag release `v0.2.0`
