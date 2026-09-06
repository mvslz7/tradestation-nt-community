"""
Tests for TradeStation client factory wiring.
"""

from unittest.mock import MagicMock

import pytest

from tradestation_nt_community.config import TradeStationExecClientConfig
from tradestation_nt_community.factories import get_cached_tradestation_http_client
from tradestation_nt_community.factories import get_cached_tradestation_instrument_provider


class _CapturingExecutionClient:
    """Stand-in for TradeStationExecutionClient that records its constructor kwargs."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        _CapturingExecutionClient.last_kwargs = kwargs


@pytest.fixture(autouse=True)
def _clear_factory_caches():
    get_cached_tradestation_http_client.cache_clear()
    get_cached_tradestation_instrument_provider.cache_clear()
    yield
    get_cached_tradestation_http_client.cache_clear()
    get_cached_tradestation_instrument_provider.cache_clear()


def _make_config(**overrides) -> TradeStationExecClientConfig:
    kwargs = dict(
        account_id="SIM0000001F",
        client_id="id",
        client_secret="sec",
        refresh_token="tok",
        use_sandbox=True,
    )
    kwargs.update(overrides)
    return TradeStationExecClientConfig(**kwargs)


class TestAccountTypeConfigFlowThrough:
    """
    TODO 3a: verify TradeStationExecClientConfig(account_type=...) flows through
    TradeStationLiveExecClientFactory.create() into AccountType passed to
    TradeStationExecutionClient.__init__, with MARGIN as the default.
    """

    def test_cash_account_type_resolves_to_AccountType_CASH(self, monkeypatch):
        import tradestation_nt_community.factories as factories_module
        from nautilus_trader.model.enums import AccountType

        monkeypatch.setattr(
            factories_module, "TradeStationExecutionClient", _CapturingExecutionClient,
        )

        config = _make_config(account_type="CASH")
        factories_module.TradeStationLiveExecClientFactory.create(
            loop=MagicMock(),
            name="TRADESTATION",
            config=config,
            msgbus=MagicMock(),
            cache=MagicMock(),
            clock=MagicMock(),
        )

        assert _CapturingExecutionClient.last_kwargs["account_type"] == AccountType.CASH

    def test_default_account_type_is_MARGIN(self, monkeypatch):
        import tradestation_nt_community.factories as factories_module
        from nautilus_trader.model.enums import AccountType

        monkeypatch.setattr(
            factories_module, "TradeStationExecutionClient", _CapturingExecutionClient,
        )

        config = _make_config()  # account_type defaults to "MARGIN"
        factories_module.TradeStationLiveExecClientFactory.create(
            loop=MagicMock(),
            name="TRADESTATION",
            config=config,
            msgbus=MagicMock(),
            cache=MagicMock(),
            clock=MagicMock(),
        )

        assert _CapturingExecutionClient.last_kwargs["account_type"] == AccountType.MARGIN

    def test_invalid_account_type_falls_back_to_MARGIN(self, monkeypatch):
        """An unrecognised account_type string shouldn't raise — factories.py
        catches the KeyError and falls back to MARGIN."""
        import tradestation_nt_community.factories as factories_module
        from nautilus_trader.model.enums import AccountType

        monkeypatch.setattr(
            factories_module, "TradeStationExecutionClient", _CapturingExecutionClient,
        )

        config = _make_config(account_type="NOT_A_REAL_TYPE")
        factories_module.TradeStationLiveExecClientFactory.create(
            loop=MagicMock(),
            name="TRADESTATION",
            config=config,
            msgbus=MagicMock(),
            cache=MagicMock(),
            clock=MagicMock(),
        )

        assert _CapturingExecutionClient.last_kwargs["account_type"] == AccountType.MARGIN
