# Options Support — Implementation Plan

## Status

The adapter currently supports `OptionContract` **loading and market data** but not
**order submission**. This plan covers adding full execution support.

## API Findings (from TradeStation OpenAPI Spec)

Source: [TradeStation API spec](https://raw.githubusercontent.com/tradestation/api-docs/master/spec/swagger.yaml)

### TradeAction Values for Options

Options use **different** TradeAction values than equities/futures:

| Asset Type      | TradeAction values                                        |
| --------------- | --------------------------------------------------------- |
| Equities/Futures | `BUY`, `SELL`, `BUYTOCOVER`, `SELLSHORT`                 |
| **Options**     | `BUYTOOPEN`, `BUYTOCLOSE`, `SELLTOOPEN`, `SELLTOCLOSE`   |

### New Required Field: `AssetType`

The `POST /orderexecution/orders` body requires an `AssetType` field:

| Value | Meaning        |
| ----- | -------------- |
| `EQ`  | Equity / Stock |
| `FU`  | Future         |
| `OP`  | Option         |

The current adapter does **not** send this field — TS infers it for equities/futures,
but it is required for options.

### Same Endpoint

Options use `POST /v3/orderexecution/orders` — the same endpoint as equities and futures.
No separate URL is needed.

### Route Field

For options, `Route` defaults to `"Intelligent"`. Since the API does not require it, we will
**not** set it.

### Design Decision: Simple TradeAction Mapping

Since NautilusTrader `Order` objects only carry `BUY`/`SELL` (no "position effect" field),
and we avoid business logic on the adapter side, the mapping is straightforward:

| NT `OrderSide` | TS TradeAction for Options |
| -------------- | -------------------------- |
| `BUY`          | `BUYTOOPEN`                |
| `SELL`         | `SELLTOOPEN`                |

Strategies requiring `BUYTOCLOSE`/`SELLTOCLOSE` can be supported later via a keyword
argument override if needed.

---

## Implementation Phases

### Phase 1: Core Order Conversion (parsing layer + HTTP client)

**1a. `parsing/execution.py` — `convert_order_to_ts_format()`**

Add option-specific TradeAction and AssetType to the return dict:

```python
# When order.instrument is OptionContract:
params["trade_action"] = "BUYTOOPEN" if order.side == OrderSide.BUY else "SELLTOOPEN"
params["asset_type"] = "OP"
```

| Change                       | Lines |
| ---------------------------- | ----- |
| Accept optional `asset_type` param | +5    |
| Return `asset_type` in dict when present | +2    |
| Re-export `OptionContract` type check helper | +3    |

**1b. `http/client.py` — `place_order()`**

Accept optional `asset_type` parameter; include `"AssetType"` in the JSON body when set.

| Change                                    | Lines |
| ----------------------------------------- | ----- |
| Add `asset_type: str \| None = None` param | +1    |
| Conditionally include `"AssetType"` key   | +3    |

**1c. `http/client.py` — `place_order_group()`**

Same `asset_type` passthrough for each leg in group orders.

| Change                                    | Lines |
| ----------------------------------------- | ----- |
| Add `asset_type` param                    | +1    |
| Inject `AssetType` into each leg payload  | +3    |

---

### Phase 2: Execution Client Changes

**2a. `execution.py` — `_convert_order_to_ts_format()` (method override)**

Detect `OptionContract` instruments and apply option-specific mappings:

```python
from nautilus_trader.model.instruments import OptionContract
if isinstance(instrument, OptionContract):
    params["trade_action"] = "BUYTOOPEN" if order.side == OrderSide.BUY else "SELLTOOPEN"
    params["asset_type"] = "OP"
```

| Change                                             | Lines |
| -------------------------------------------------- | ----- |
| Import `OptionContract`                            | +1    |
| Add `isinstance(instrument, OptionContract)` branch | +10   |

**2b. `execution.py` — `__init__()` — Make account type configurable**

Current hardcoded value: `account_type=AccountType.MARGIN`

| Change                                    | Lines |
| ----------------------------------------- | ----- |
| Accept `account_type` param in constructor | +1    |
| Use config-provided value instead of hardcoded `MARGIN` | +1    |

---

### Phase 3: Configuration

**3a. `config.py` — `TradeStationExecClientConfig`**

| Change                              | Lines |
| ----------------------------------- | ----- |
| Add `account_type: str = "MARGIN"`  | +1    |

**3b. `factories.py` — `TradeStationLiveExecClientFactory.create()`**

| Change                                      | Lines |
| ------------------------------------------- | ----- |
| Pass `config.account_type` to client constructor | +1    |

---

### Phase 4: Tests

#### 4a. New Test Fixtures (`tests/resources/`)

| File                                  | Purpose                                                |
| ------------------------------------- | ------------------------------------------------------ |
| `order_option_market_filled.json`     | Filled option market order (AssetType=OP, TradeAction=BUYTOOPEN) |
| `order_option_limit_open.json`        | Open option limit order                                 |
| `place_order_option_response.json`    | Successful option order placement response              |

These mirror the existing `order_market_filled.json`, `order_limit_open.json`, and
`place_order_response.json` but with option-specific `AssetType` and `TradeAction` fields.

#### 4b. `tests/test_parsing.py` — New Tests

**Class: `TestConvertOrderToTsFormatOptions`**

| Test                                       | Verifies                                                      |
| ------------------------------------------ | ------------------------------------------------------------- |
| `test_convert_market_buy_option`           | BUY + OptionContract → `trade_action="BUYTOOPEN"`             |
| `test_convert_limit_sell_option`           | SELL + OptionContract → `trade_action="SELLTOOPEN"`           |
| `test_convert_stop_market_option`          | StopMarket + OptionContract → `SELLTOOPEN`, `stop_price` preserved |
| `test_convert_stop_limit_option`           | StopLimit + OptionContract → both `stop_price` and `limit_price` |
| `test_convert_option_passes_asset_type`     | Result dict contains `asset_type="OP"`                        |
| `test_convert_option_symbol_occ_format`     | Symbol with spaces preserved (e.g. `"AAPL 250321C00175000"`) |

**Class: `TestParseFillReport` (additions)**

| Test                                     | Verifies                                              |
| ---------------------------------------- | ----------------------------------------------------- |
| `test_parse_fill_report_for_option`      | Fill report parses BUYTOOPEN → BUY side correctly     |

**Class: `TestParseOrderStatusReport` (additions)**

| Test                                     | Verifies                                              |
| ---------------------------------------- | ----------------------------------------------------- |
| `test_parse_option_order_status_report`  | OrderStatusReport for option: BUYTOOPEN → BUY mapping |

#### 4c. `tests/test_execution.py` — New Tests

**Class: `TestOptionOrderConversion`**

| Test                                            | Verifies                                                     |
| ----------------------------------------------- | ------------------------------------------------------------ |
| `test_option_instrument_detected`               | Cache returns OptionContract → `asset_type="OP"` set          |
| `test_option_market_buy_maps_to_buytoopen`      | OrderSide.BUY + OptionContract → TradeAction BUYTOOPEN        |
| `test_option_market_sell_maps_to_selltoopen`    | OrderSide.SELL + OptionContract → TradeAction SELLTOOPEN      |
| `test_option_stop_limit_buytoopen`              | StopLimit BUY + OptionContract → BUYTOOPEN with stop+limit    |
| `test_option_symbol_preserved_in_params`        | OCC symbol `"AAPL 250321C00175000"` passed through unchanged  |
| `test_equity_still_uses_buy_sell`               | **Regression:** equity TradeAction logic unchanged             |
| `test_futures_still_uses_buy_sell`              | **Regression:** futures TradeAction logic unchanged            |

**Class: `TestSubmitOrderGroups` / order-group tests (additions)**

| Test                                          | Verifies                                               |
| --------------------------------------------- | ------------------------------------------------------ |
| `test_oco_option_group_has_asset_type`        | Each leg in an option OCO group gets `AssetType="OP"`  |

#### 4d. `tests/test_http_client.py` — New Tests

| Test                                            | Verifies                                                     |
| ----------------------------------------------- | ------------------------------------------------------------ |
| `test_place_order_includes_asset_type_when_set` | `asset_type="OP"` → JSON body contains `"AssetType": "OP"`   |
| `test_place_order_omits_asset_type_when_none`   | Default `None` → JSON body does **not** contain `AssetType`   |
| `test_place_order_group_includes_asset_type`    | Group order legs pass through `asset_type` param              |

#### 4e. Config Tests (in `test_execution.py` or `test_config.py`)

| Test                                      | Verifies                                          |
| ----------------------------------------- | ------------------------------------------------- |
| `test_exec_config_account_type_default`   | Default is `"MARGIN"`                             |
| `test_exec_config_account_type_cash`      | Can set to `"CASH"`                               |
| `test_account_type_flows_to_client`       | Value reaches `TradeStationExecutionClient.__init__` |

#### 4f. Mock Client Updates (`tests/mock_http_client.py`)

| Change                                      | Reason                                          |
| ------------------------------------------- | ----------------------------------------------- |
| `place_order()`: add `asset_type` param     | Verify it is passed through                     |
| `get_orders()`: return option order fixture | Needed for reconciliation tests                 |
| `get_symbol_details()`: detect option OCC   | Already partially there (`" " in symbol`)       |

#### 4g. Test Kit Updates (`tests/test_kit.py`)

**New stub method: `TSTestInstrumentStubs.aapl_call_option()`**

Returns a pre-built `OptionContract` matching `symbol_detail_option.json` fixture data.
Used by both parsing and execution tests to avoid constructing instruments inline.

---

### Phase 5: Sandbox Validation

**Prerequisites:** TradeStation sandbox credentials with options trading enabled on the account.

#### Stage 5.1 — Instrument Loading (can run before code changes)

- [ ] Load a known option instrument via `get_symbol_details()`
      (e.g. AAPL or SPY near-term weekly option)
- [ ] Verify the API returns `AssetType: "OPTION"` with all expected fields
- [ ] Confirm OCC symbol format (`"AAPL 250321C00175000"`) works with the TS API
- [ ] Verify `parse_instrument()` → `OptionContract` round-trips correctly
- [ ] Log the raw API response for comparison with existing `symbol_detail_option.json`

#### Stage 5.2 — Market Data (can run before code changes)

- [ ] Subscribe to quote stream for an option symbol (SSE + polling)
- [ ] Subscribe to bar stream for an option symbol
- [ ] Verify data flows correctly (should work since data client is symbol-based)

#### Stage 5.3 — Order Submission (after Phase 1-3 code changes)

- [ ] Place a BUYTOOPEN limit order far OTM (won't fill) → verify acceptance
- [ ] Place a SELLTOOPEN limit order → verify acceptance
- [ ] Verify `OrderID` is returned and tracked in the ID maps
- [ ] Cancel the unfilled orders → verify cancellation event
- [ ] Modify an option order (change limit price) → verify modification event
- [ ] Place a Market order → verify immediate fill detection (SSE or polling)

#### Stage 5.4 — Fill Detection & Reconciliation

- [ ] Verify `generate_fill_reports()` includes the option fill
- [ ] Verify `generate_position_status_reports()` includes the option position
- [ ] Restart the node → verify reconciliation recovers option orders/positions
- [ ] Verify `generate_order_status_reports()` shows option orders with correct status

#### Stage 5.5 — Edge Cases

- [ ] Expired option: place a GTC order, let it expire → verify EXP status handling
- [ ] Rejected order: place with invalid price → verify REJ status and error message
- [ ] Option with spaces in symbol: verify all endpoints handle OCC format
- [ ] Zero-bid/ask options (illiquid strikes): verify quote handling doesn't crash
- [ ] Option volume = 0: verify bar/tick subscription doesn't error

---

### Phase 6: Documentation

| File                    | Change                                                       |
| ----------------------- | ------------------------------------------------------------ |
| `README.md`             | Remove "(loading only)" qualifier; add options to execution features table |
| `CLAUDE.md`             | Update "Known Constraints" — remove options execution gap    |
| `docs/tradestation.md`  | Update "Instruments" table: `OptionContract` → full support  |
| `docs/tradestation.md`  | Update "Known Limitations" — remove "No options execution"   |

---

## Summary of File Changes

| File                                  | Status   | Est. Lines |
| ------------------------------------- | -------- | ---------- |
| `parsing/execution.py`                | Modified | +15        |
| `http/client.py`                      | Modified | +10        |
| `execution.py`                        | Modified | +30        |
| `config.py`                           | Modified | +3         |
| `factories.py`                        | Modified | +2         |
| `tests/resources/order_option_*.json` | New ×3   | ~150       |
| `tests/test_parsing.py`               | Modified | +80        |
| `tests/test_execution.py`             | Modified | +60        |
| `tests/test_http_client.py`           | Modified | +40        |
| `tests/mock_http_client.py`           | Modified | +5         |
| `tests/test_kit.py`                   | Modified | +20        |
| `README.md`                           | Modified | ~5         |
| `CLAUDE.md`                           | Modified | ~3         |
| `docs/tradestation.md`                | Modified | ~5         |
| **Total**                             |          | **~430**   |

## Test Coverage Target

- **Parsing layer:** 100% — pure functions, easy to test in isolation
- **HTTP client:** 100% — mock-based, all `AssetType` variations covered
- **Execution client:** Core conversion path + regression paths (equity/futures unchanged)
- **Sandbox:** Every order type + fill + reconciliation + edge cases documented above
