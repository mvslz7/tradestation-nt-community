# Security Review: tradestation-nt-community

**Date:** 2026-04-14
**Scope:** Full review of the `tradestation_nt_community` package for injection vulnerabilities, authentication/authorization flaws, credential handling, and insecure data handling.

---

## HIGH Severity

### 1. API response bodies leaked in exception messages -- FIXED

**Status:** Resolved.

All 13 error sites in `http/client.py` now log the full `response.text` at DEBUG level (truncated to 500 chars) and raise exceptions with only the HTTP status code.

Order-execution endpoints (place, replace, cancel, place_group) additionally include a truncated (200 char) response excerpt in the exception message. This is required because `execution.py` parses exception text to detect specific broker conditions (e.g. `"Not an open order"` for expired DAY orders on cancel).

---

### 2. Credentials stored as public attributes with no cleanup -- FIXED

**Status:** Resolved.

- `client_secret` and `refresh_token` are now private (`self._client_secret`, `self._refresh_token`).
- `access_token` is now a read-only property backed by `self._access_token`.
- `client_id` remains public (app identifier, not a secret).
- `close()` clears all credentials (`_access_token`, `_client_secret`, `_refresh_token`, `token_expiry`) before closing the HTTP client.

**Remaining note:** `factories.py` `@lru_cache(1)` still holds credential strings in the cache key. This is a minor residual risk -- the cache prevents duplicate clients but keeps one copy of credentials immune to GC.

---

### 3. Unvalidated `base_url` override enables credential theft -- FIXED

**Status:** Resolved.

`http/client.py` now validates that `base_url` uses HTTPS and points to a known TradeStation domain (`api.tradestation.com`, `sim-api.tradestation.com`). Rejects plain HTTP and unknown hosts with a `ValueError`.

An `allow_custom_base_url=True` flag (available in both config classes and the HTTP client) bypasses the check for local proxies or mock servers. Defaults to `False`.

---

## MEDIUM Severity

### 4. Query string injection in `stream_bars()` -- FIXED

**Status:** Resolved.

`stream_bars()` now passes query parameters as a dict via httpx's `params` kwarg instead of manual f-string concatenation. The `_stream()` core method accepts an optional `params` dict and forwards it to `client.stream()`, which handles URL encoding.

**Previously:**

```python
params = f"?interval={interval}&unit={unit}&barsback=1"
if session_template:
    params += f"&sessiontemplate={session_template}"
async for event in self._stream(url + params):
```

**Now:**

```python
params = {"interval": interval, "unit": unit, "barsback": "1"}
if session_template:
    params["sessiontemplate"] = session_template
# Pass params to the stream method instead of concatenating
```

---

### 5. User-supplied values interpolated into URL paths without encoding -- FIXED

**Status:** Resolved.

All path segments built from caller-supplied values (`symbol`, `search_text`, `underlying`, `account_keys`, `order_id`, `symbols`) are now passed through `urllib.parse.quote()` in both `http/client.py` and `streaming/client.py`, with `safe=","` where TradeStation accepts comma-separated lists (account keys, quote symbols) and `safe="$"` preserved for index symbols like `$SPX.X`. Verified against the live sandbox that `$SPX.X`, comma-separated multi-symbol quotes, and space-containing OCC option symbols (e.g. `AAPL 260909C310`) all still resolve correctly post-encoding.

---

### 6. SSE streaming client disables timeouts entirely -- FIXED

**Status:** Resolved (prior to this review's fix pass — already addressed as part of the §70 stale-stream-reconnect fix).

`streaming/client.py`'s `_stream()` now uses a bounded timeout: `httpx.Timeout(connect=30.0, read=90.0, write=None, pool=30.0)`. A 90-second read timeout without any data (including heartbeats) is treated as a zombie connection and triggers an immediate reconnect rather than hanging indefinitely.

---

### 7. Account ID embedded in logged SSE URLs -- FIXED

**Status:** Resolved.

All URLs logged from `streaming/client.py` (`SSE stream connected`, `SSE stream error`, `SSE stream cancelled`, the non-200 response log, and the zombie-reconnect warning) now pass through `_redact_account()`, which replaces the `/accounts/{id}/` path segment with `/accounts/***/` before logging. Order-stream URLs (the only ones containing an account ID) no longer accumulate the account ID in log files; quote/bar/depth URLs are unaffected since they don't contain one.

---

## LOW Severity

### 8. Deprecated `datetime.utcnow()` -- FIXED

**Status:** Resolved. Replaced with `datetime.now(tz=timezone.utc)` in `http/client.py` and tests.

---

### 9. No response size bounds on JSON parsing -- FIXED

**Status:** Resolved.

All `response.json()` calls in `http/client.py` now go through a `_safe_json()` wrapper that checks `len(response.content)` against a 25 MB cap and raises `ValueError` before parsing if exceeded. This doesn't prevent httpx from buffering an oversized body in the first place (that would require streaming the response), but it stops the more expensive `json.loads()` deserialization step from running on a pathological body — relevant only if `base_url` is overridden (see finding #3).

---

## Positive Findings

- **No hardcoded credentials** anywhere in source, tests, or examples.
- **`.gitignore` properly excludes `.env`** files.
- **TLS enforced** -- all default URLs use HTTPS; `verify=True` is httpx's default.
- **No dangerous deserialization** -- no `eval()`, `exec()`, `pickle`, `subprocess`, or `yaml.load()`.
- **Order bodies use `json=` parameter** -- properly JSON-encoded, no string interpolation in request bodies.
- **Test fixtures use mock values** (`"mock_client_id"`, `"test_client_id"`) -- no real credentials.
- **SSE reconnect has exponential backoff with cap** (8x initial delay) -- prevents reconnect storms.
- **httpx defaults to `follow_redirects=False`** -- mitigates SSRF via redirect chains.
- **No data written to disk** -- all credential and trading data is in-memory only.

---

## Summary

| # | Finding | Severity | Location |
|---|---------|----------|----------|
| 1 | Raw `response.text` in exceptions / logs | **HIGH** | `http/client.py` (13 locations) |
| 2 | Credentials as public attrs, no cleanup | **HIGH** | `http/client.py:47-49,66`, `factories.py:21` |
| 3 | Unvalidated `base_url` enables credential theft | **HIGH** | `config.py:47,98`, `http/client.py:59` |
| 4 | Query string injection in `stream_bars()` | **MEDIUM** | `streaming/client.py:179-183` — FIXED |
| 5 | URL path segments not encoded | **MEDIUM** | `http/client.py` (10 sites), `streaming/client.py` (4 sites) — FIXED |
| 6 | SSE client `timeout=None` | **MEDIUM** | `streaming/client.py:91` — FIXED |
| 7 | Account ID in log messages | **MEDIUM** | `streaming/client.py:96,103,123,126` — FIXED |
| 8 | Deprecated `datetime.utcnow()` | **LOW** | `http/client.py:82,98` — FIXED |
| 9 | No response size bounds | **LOW** | `http/client.py` (all `.json()` calls) — FIXED |

All findings from this review are now resolved.
