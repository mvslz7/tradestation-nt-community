"""
Regression test for TradeStationDataClient._request_instrument().

Nautilus's LiveMarketDataClient.request_instrument() calls
self._request_instrument(request) with a single RequestInstrument message
object (see nautilus_trader/live/data_client.py). An earlier version of
this method took unpacked (instrument_id, correlation_id, start, end)
arguments instead -- a version-skew bug that raised a TypeError as soon as
any strategy called self.request_instrument(), killing the node before the
instrument ever loaded. This test pins the correct signature and response
handling (_handle_instrument, not the generic _handle_data).
"""

import asyncio

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.data.messages import RequestInstrument
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from tests.mock_http_client import MockTradeStationHttpClient
from tradestation_nt_community.data import TradeStationDataClient
from tradestation_nt_community.providers import TradeStationInstrumentProvider


async def test_request_instrument_loads_and_hands_back_via_handle_instrument():
    clock = TestComponentStubs.clock()
    cache = TestComponentStubs.cache()
    msgbus = TestComponentStubs.msgbus()
    provider = TradeStationInstrumentProvider(client=MockTradeStationHttpClient())

    client = TradeStationDataClient(
        loop=asyncio.get_running_loop(),
        client=MockTradeStationHttpClient(),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=provider,
    )

    handled = []
    client._handle_instrument = lambda *args: handled.append(args)

    instrument_id = InstrumentId.from_str("AAPL.TRADESTATION")
    request = RequestInstrument(
        instrument_id=instrument_id,
        start=None,
        end=None,
        client_id=None,
        venue=instrument_id.venue,
        callback=lambda *a, **kw: None,
        request_id=UUID4(),
        ts_init=clock.timestamp_ns(),
        params={},
    )

    await client._request_instrument(request)

    assert len(handled) == 1
    instrument, correlation_id, start, end, params = handled[0]
    assert instrument.id == instrument_id
    assert correlation_id == request.id
    assert cache.instrument(instrument_id) is not None
