# TODO — Options Support

## Status

Source code and test files are written and compile cleanly.  Not yet executed
because the environment lacks `pip` and the NautilusTrader runtime.

---

## Blockers

- [ ] **Install pip + dev dependencies**

  ```bash
  # In whatever Python 3.12.13 environment is available:
  python3 -m ensurepip --upgrade
  python3 -m pip install -e "/workspace[dev]"
  ```

  This must succeed before unit tests or sandbox tests can run.

---

## 1. Run unit tests

```bash
cd /workspace
pytest tests/ -q
```

Expected: all existing tests pass, ~23 new option-specific tests pass.

If tests fail, check:
- NautilusTrader version (`pip show nautilus-trader`) — adapter requires `>=1.200`
- Test fixtures in `tests/resources/` are present (3 new JSON files)

---

## 2. Sandbox validation

Requires TradeStation sandbox credentials with options trading enabled.

```bash
export TRADESTATION_CLIENT_ID="..."
export TRADESTATION_CLIENT_SECRET="..."
export TRADESTATION_REFRESH_TOKEN="..."
export TRADESTATION_ACCOUNT_ID="SIM..."

cd /workspace
python3 tests/sandbox_validate_options.py
```

The script dynamically discovers a valid option instrument — no hardcoded
contracts that expire.

Can also specify a different underlying:

```bash
python3 tests/sandbox_validate_options.py --underlying SPY
```

### Sandbox checklist

- [ ] **Phase 1: Instrument loading** — option discovered and parsed as `OptionContract`
- [ ] **Phase 2: Market data** — quotes/ticks received for the option symbol
- [ ] **Phase 3a: Order placement** — `BuyToOpen` limit order accepted, `OrderID` returned, `AssetType: OP` present in request
- [ ] **Phase 3b: Order verify** — order visible in `GET /orders`
- [ ] **Phase 3c: Order cancel** — cancellation confirmed
- [ ] **Phase 4: Reconciliation** — fill reports and order status reports parse correctly for option orders

---

## 3. Gaps to address after sandbox validation

### 3a. Account type config test

Write a unit test that verifies:
- `TradeStationExecClientConfig(account_type="CASH")` flows through the factory into `TradeStationExecutionClient.__init__` as `AccountType.CASH`
- Default remains `AccountType.MARGIN`

This was skipped because it requires the NautilusTrader runtime to resolve `AccountType`.

### 3b. SSE streaming with option symbols

The SSE streaming client (`streaming/client.py`) is symbol-based, so it
*should* work for options without changes.  Verify in sandbox:

```python
stream_client = TradeStationStreamClient(...)
async for event in stream_client.stream_quotes("AAPL 260530C00175000"):
    print(event)  # expect Bid/Ask/Last for the option
```

### 3c. `BuyToClose` / `SellToClose` support

Current mapping is simple:
```
BUY  → BuyToOpen
SELL → SellToOpen
```

If a strategy needs to close positions, add an optional `trade_action_override`
keyword argument to `_submit_order` / `_convert_order_to_ts_format`.

### 3d. Options example script

Create `examples/tradestation_options_example.py` based on the existing
`tradestation_example.py` but using a dynamically-discovered option.

---

## 4. Pre-release checklist

- [ ] All unit tests pass (`pytest tests/ -q`)
- [ ] Sandbox validation passes (all 4 phases)
- [ ] Regression: existing futures + equities still work (run existing examples)
- [ ] README / CLAUDE.md / docs updated (already done)
- [ ] CHANGELOG entry (if applicable)
- [ ] Tag release `v0.2.0`
