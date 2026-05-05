from __future__ import annotations

import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from pm_bot.cli.trade import run_trade, _resolve_cities, _resolve_strategies, fetch_forecast_at, _setup_logging


class TestResolveCities:
    def test_all_cities(self):
        result = _resolve_cities(None, True)
        assert result == set()

    def test_cities_str(self):
        result = _resolve_cities("NYC,HK", False)
        assert "New York" in result

    def test_default(self):
        result = _resolve_cities(None, False)
        assert len(result) > 0


class TestResolveStrategies:
    def test_all(self):
        result = _resolve_strategies("all")
        assert len(result) > 0

    def test_specific(self):
        result = _resolve_strategies("gopfan2")
        assert result[0][0] == "gopfan2"

    def test_unknown(self):
        result = _resolve_strategies("nonexistent")
        assert result == []


class TestSetupLogging:
    def test_debug(self):
        _setup_logging(debug=True)

    def test_no_debug(self):
        _setup_logging(debug=False)


class TestRunTrade:
    @patch("pm_bot.cli.trade.load_config", return_value={})
    @patch("pm_bot.cli.trade.ClobTrader")
    @patch("pm_bot.cli.trade.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_no_events(self, mock_events, mock_trader_cls, mock_config):
        mock_events.return_value = []
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader_cls.return_value = mock_trader
        await run_trade()

    @patch("pm_bot.cli.trade.render_recommendations")
    @patch("pm_bot.cli.trade.fetch_forecast", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.ClobTrader")
    @patch("pm_bot.cli.trade.load_config", return_value={})
    @pytest.mark.asyncio
    async def test_confirm_not_configured(self, mock_config, mock_trader_cls,
                                            mock_events, mock_forecast, mock_render):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = False
        mock_trader_cls.return_value = mock_trader
        await run_trade(confirm=True)

    @patch("pm_bot.cli.trade.render_recommendations")
    @patch("pm_bot.cli.trade.fetch_forecast", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.ClobTrader")
    @patch("pm_bot.cli.trade.load_config", return_value={})
    @pytest.mark.asyncio
    async def test_with_events_no_confirm(self, mock_config, mock_trader_cls,
                                           mock_events, mock_forecast, mock_render):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        mock_forecast.return_value = None
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader_cls.return_value = mock_trader
        await run_trade()

    @patch("pm_bot.cli.trade.render_recommendations")
    @patch("pm_bot.cli.trade.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.trade.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.ClobTrader")
    @patch("pm_bot.cli.trade.load_config", return_value={})
    @pytest.mark.asyncio
    async def test_all_cities_filter(self, mock_config, mock_trader_cls,
                                      mock_events, mock_forecast, mock_render):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader_cls.return_value = mock_trader
        await run_trade(all_cities=True)

    @patch("pm_bot.cli.trade.render_recommendations")
    @patch("pm_bot.cli.trade.fetch_forecast", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.ClobTrader")
    @patch("pm_bot.cli.trade.load_config", return_value={})
    @pytest.mark.asyncio
    async def test_with_station_and_city_coords(self, mock_config, mock_trader_cls,
                                                  mock_events, mock_forecast, mock_render):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        fc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                            temp_high_c=23.0, members=[23.0])
        mock_forecast.return_value = fc
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader_cls.return_value = mock_trader
        with patch("pm_bot.cli.trade.get_station_for_city", return_value={"lat": 40.7, "lon": -74.0}):
            afc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                                 temp_high_c=24.0, members=[24.0])
            with patch("pm_bot.cli.trade.fetch_forecast_at", new_callable=AsyncMock, return_value=afc):
                await run_trade(cities_str="NYC")

    @patch("pm_bot.cli.trade.render_recommendations")
    @patch("pm_bot.cli.trade.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.trade.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.ClobTrader")
    @patch("pm_bot.cli.trade.load_config", return_value={})
    @pytest.mark.asyncio
    async def test_observed_filter(self, mock_config, mock_trader_cls,
                                    mock_events, mock_forecast, mock_render):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader_cls.return_value = mock_trader
        with patch("pm_bot.cli.trade.fetch_observation", new_callable=AsyncMock, return_value=None):
            await run_trade(observed=True, cities_str="NYC")

    @patch("pm_bot.cli.trade.render_recommendations")
    @patch("pm_bot.cli.trade.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.trade.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.ClobTrader")
    @patch("pm_bot.cli.trade.load_config", return_value={})
    @pytest.mark.asyncio
    async def test_confirm_with_trade(self, mock_config, mock_trader_cls,
                                       mock_events, mock_forecast, mock_render):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.50, no_price=0.50, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.daily_spent = 0.0
        mock_trader_cls.return_value = mock_trader
        with patch("pm_bot.cli.trade.Confirm.ask", return_value=False):
            with patch("pm_bot.core.config_loader.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
                await run_trade(confirm=True, cities_str="NYC")

    @patch("pm_bot.cli.trade.render_recommendations")
    @patch("pm_bot.cli.trade.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.trade.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.trade.ClobTrader")
    @patch("pm_bot.cli.trade.load_config", return_value={})
    @pytest.mark.asyncio
    async def test_edge_override(self, mock_config, mock_trader_cls,
                                  mock_events, mock_forecast, mock_render):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader_cls.return_value = mock_trader
        await run_trade(edge_override=0.20, cities_str="NYC")


class TestFetchForecastAt:
    @pytest.mark.asyncio
    async def test_http_error(self):
        import httpx
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError("fail")
        result = await fetch_forecast_at(mock_client, 40.0, -74.0, "NYC")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0]},
        }
        resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=resp)
        result = await fetch_forecast_at(mock_client, 40.0, -74.0, "NYC", "2026-01-15")
        assert result is not None
        assert result.temp_high_c == 25.0

    @pytest.mark.asyncio
    async def test_no_temp_in_response(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"daily": {"temperature_2m_max": []}}
        resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=resp)
        result = await fetch_forecast_at(mock_client, 40.0, -74.0, "NYC")
        assert result is not None
        assert result.temp_high_c == 0.0

    @pytest.mark.asyncio
    async def test_with_ensemble_members(self):
        mock_client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0]},
        }
        main_resp.raise_for_status = MagicMock()
        ens_resp = MagicMock()
        ens_resp.json.return_value = {
            "daily": {
                "temperature_2m_max": [25.0],
                "temperature_2m_max_member01": [24.0],
                "temperature_2m_max_member02": [26.0],
            },
        }
        ens_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(side_effect=[main_resp, ens_resp])
        result = await fetch_forecast_at(mock_client, 40.0, -74.0, "NYC")
        assert result is not None
        assert len(result.members) == 2

    @pytest.mark.asyncio
    async def test_ensemble_http_error(self):
        import httpx
        mock_client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0]},
        }
        main_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(side_effect=[main_resp, httpx.HTTPError("fail")])
        result = await fetch_forecast_at(mock_client, 40.0, -74.0, "NYC")
        assert result is not None
        assert result.temp_high_c == 25.0
        assert result.members == []
