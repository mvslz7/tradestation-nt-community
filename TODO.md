# TODO — Options Support

## Status

Source, tests, and sandbox validation are all runnable in this environment
(`.venv` has `nautilus_trader==1.227.0` installed). 392/392 unit tests pass.

`tests/sandbox_validate_options.py` has been run live against the TradeStation
sandbox (2026-09-06, market closed — see "Sandbox validation" below for what
that does and doesn't prove). Every run logs to both the console and a
timestamped file under `logs/` (git-ignored) so an unattended/scheduled run
can be diagnosed after the fact without anyone watching it live.

---

## Sandbox validation

```bash
cd /home/ubuntu/workarea/tradestation-nt-community
.venv/bin/python tests/sandbox_validate_options.py
# Or with a different underlying:
.venv/bin/python tests/sandbox_validate_options.py --underlying SPY --index '$SPX.X'
```

Credentials are already populated in `.env` (client ID/secret, refresh token,
sim account ID) — no setup needed to run this.

### What's been confirmed (market-closed run, 2026-09-06)

- [x] **Phase 1: Instrument loading** — option discovered and parsed as `OptionContract`
- [x] **Phase 2: Market data** — quotes received for the option symbol
- [x] **Phase 2b: SSE quote streaming** — connects and delivers quote events for an
      option symbol even with the market closed (validates the pipeline end-to-end;
      previously unverified — see "Gaps" §3b below, now resolved)
- [x] **Phase 3: Order lifecycle** — symbol/order format accepted by the order
      engine; sandbox correctly rejects DAY orders when the market is closed
      ("Only GTC/GTC+/GTD/GTD+ orders when markets are closed") — this is
      TradeStation's real business rule, not a code bug, and the script now
      classifies it as an expected warning rather than a failure
- [x] **Phase 3f: Deliberate rejection** — an intentionally invalid order
      (quantity=0) is rejected by TradeStation (HTTP 400, not the 200+FAILED
      body-error shape `OrderRejectedException` targets — logged as a WARN
      noting the exception type differs from what was expected)
- [x] **Phase 4: Reconciliation** — order listing fetch and report parsing work
- [x] **Phase 5/6: Index + index option loading** — `$SPX.X` and a discovered
      index option both parse correctly (INDEX asset class)

### What still needs a market-hours run

Order **placement→fill** and **modify** against a live order book haven't been
exercised — the market-closed run above proves the code path is reachable and
correctly formatted, but DAY limit orders are rejected before they reach the
matching engine when the market is closed. A local cron job runs this script
automatically at ~11:30 ET on the next trading day (see `README.md` /
crontab) so this gets exercised without anyone needing to be online watching
market open. Check `logs/` for the result.

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
discovery approach as `sandbox_validate_options.py`).

---

## Pre-release checklist

- [x] All unit tests pass (`pytest tests/ -q`) — 392 passing
- [x] Sandbox validation passes for all reference-data/parsing/streaming
      phases; order fill/modify against a live book pending a market-hours run
- [ ] Regression: existing futures + equities still work (run existing examples)
- [x] README / CLAUDE.md / docs updated
- [ ] CHANGELOG entry (if applicable)
- [ ] Tag release `v0.2.0`
