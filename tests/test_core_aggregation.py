from __future__ import annotations

import pytest

from unittest.mock import AsyncMock, patch

from pm_bot.core.aggregation import (
    consensus_bucket_probability,
    fetch_all_sources,
    bucket_probability_normal,
    compute_bma_weights,
    compute_consensus_probability,
    compute_agreement_score,
    _norm_cdf,
)
from pm_bot.models.forecast import ConsensusForecast, SourceForecast


class TestNormCdf:
    def test_at_zero(self):
        assert abs(_norm_cdf(0) - 0.5) < 0.001

    def test_at_2(self):
        assert abs(_norm_cdf(2) - 0.9772) < 0.01

    def test_at_minus_2(self):
        assert abs(_norm_cdf(-2) - 0.0228) < 0.01

    def test_symmetry(self):
        assert abs(_norm_cdf(1.5) - (1.0 - _norm_cdf(-1.5))) < 0.001


class TestBucketProbabilityNormal:
    def test_celsius_bucket(self):
        p = bucket_probability_normal(mean=25.0, std=2.0, low=24.0, high=24.0, temp_unit="C")
        assert 0 < p < 1

    def test_fahrenheit_bucket(self):
        p = bucket_probability_normal(mean=33.0, std=2.0, low=32.0, high=33.5, temp_unit="F")
        assert 0 < p < 1

    def test_zero_std(self):
        p = bucket_probability_normal(mean=25.0, std=0.0, low=24.0, high=24.0, temp_unit="C")
        assert 0 < p < 1

    def test_bounded(self):
        p = bucket_probability_normal(mean=25.0, std=1.0, low=24.0, high=24.0, temp_unit="C")
        assert 0.0 <= p <= 1.0


class TestComputeBmaWeights:
    def test_single_source(self):
        sources = [SourceForecast(source="a", temp_high_c=25.0, std_c=2.0)]
        weights = compute_bma_weights(sources)
        assert len(weights) == 1
        assert abs(weights[0] - 1.0) < 0.001

    def test_two_sources_equal_std(self):
        sources = [
            SourceForecast(source="a", temp_high_c=25.0, std_c=2.0),
            SourceForecast(source="b", temp_high_c=27.0, std_c=2.0),
        ]
        weights = compute_bma_weights(sources)
        assert len(weights) == 2
        assert abs(weights[0] - 0.5) < 0.001

    def test_lower_std_gets_higher_weight(self):
        sources = [
            SourceForecast(source="a", temp_high_c=25.0, std_c=1.0),
            SourceForecast(source="b", temp_high_c=27.0, std_c=3.0),
        ]
        weights = compute_bma_weights(sources)
        assert weights[0] > weights[1]

    def test_empty_sources(self):
        weights = compute_bma_weights([])
        assert weights == []

    def test_weights_sum_to_one(self):
        sources = [
            SourceForecast(source="a", temp_high_c=25.0, std_c=1.0),
            SourceForecast(source="b", temp_high_c=27.0, std_c=2.0),
            SourceForecast(source="c", temp_high_c=26.0, std_c=3.0),
        ]
        weights = compute_bma_weights(sources)
        assert abs(sum(weights) - 1.0) < 0.001


class TestComputeAgreementScore:
    def test_perfect_agreement(self):
        sources = [
            SourceForecast(source="a", temp_high_c=25.0, std_c=1.0),
            SourceForecast(source="b", temp_high_c=25.0, std_c=1.0),
        ]
        score = compute_agreement_score(sources)
        assert abs(score - 1.0) < 0.001

    def test_large_disagreement(self):
        sources = [
            SourceForecast(source="a", temp_high_c=20.0, std_c=1.0),
            SourceForecast(source="b", temp_high_c=30.0, std_c=1.0),
        ]
        score = compute_agreement_score(sources)
        assert score < 0.5

    def test_single_source(self):
        sources = [SourceForecast(source="a", temp_high_c=25.0, std_c=1.0)]
        score = compute_agreement_score(sources)
        assert score == 0.5


class TestComputeConsensusProbability:
    def test_basic(self):
        sources = [
            SourceForecast(source="a", temp_high_c=25.0, std_c=2.0),
            SourceForecast(source="b", temp_high_c=26.0, std_c=2.0),
        ]
        prob = compute_consensus_probability(sources, 25.0, 25.0, "C")
        assert 0 < prob < 1

    def test_empty_sources(self):
        prob = compute_consensus_probability([], 25.0, 25.0, "C")
        assert prob == 0.5


class TestConsensusBucketProbability:
    def test_empty_sources(self):
        cf = ConsensusForecast(city="NYC", date="2026-01-15", temp_high_c=25.0, std_c=2.0)
        result = consensus_bucket_probability(cf, 24.0, 24.0)
        assert result == 0.5

    def test_single_source(self):
        sources = {"a": SourceForecast(source="a", temp_high_c=25.0, std_c=2.0)}
        cf = ConsensusForecast(city="NYC", date="2026-01-15", temp_high_c=25.0, std_c=2.0,
                               sources=sources, agreement_score=1.0)
        result = consensus_bucket_probability(cf, 24.0, 24.0)
        assert 0 < result < 1

    def test_strong_agreement_3plus_sources(self):
        sources = {
            "a": SourceForecast(source="a", temp_high_c=25.0, std_c=1.0),
            "b": SourceForecast(source="b", temp_high_c=25.1, std_c=1.0),
            "c": SourceForecast(source="c", temp_high_c=24.9, std_c=1.0),
        }
        cf = ConsensusForecast(city="NYC", date="2026-01-15", temp_high_c=25.0, std_c=1.0,
                               sources=sources, agreement_score=0.9)
        result = consensus_bucket_probability(cf, 24.0, 24.0)
        assert result > 0

    def test_moderate_agreement_2_sources(self):
        sources = {
            "a": SourceForecast(source="a", temp_high_c=25.0, std_c=1.0),
            "b": SourceForecast(source="b", temp_high_c=25.1, std_c=1.0),
        }
        cf = ConsensusForecast(city="NYC", date="2026-01-15", temp_high_c=25.0, std_c=1.0,
                               sources=sources, agreement_score=0.85)
        result = consensus_bucket_probability(cf, 24.0, 24.0)
        assert 0 < result < 1

    def test_low_agreement(self):
        sources = {
            "a": SourceForecast(source="a", temp_high_c=22.0, std_c=2.0),
            "b": SourceForecast(source="b", temp_high_c=28.0, std_c=2.0),
        }
        cf = ConsensusForecast(city="NYC", date="2026-01-15", temp_high_c=25.0, std_c=3.5,
                               sources=sources, agreement_score=0.2)
        result = consensus_bucket_probability(cf, 24.0, 24.0)
        assert 0 <= result <= 1

    def test_fahrenheit(self):
        sources = {"a": SourceForecast(source="a", temp_high_c=35.0, std_c=2.0)}
        cf = ConsensusForecast(city="MIA", date="2026-06-15", temp_high_c=35.0, std_c=2.0,
                               sources=sources, agreement_score=0.8)
        result = consensus_bucket_probability(cf, 90.0, 91.0, temp_unit="F")
        assert 0 <= result <= 1

    def test_high_prob_amplified(self):
        sources = {
            "a": SourceForecast(source="a", temp_high_c=25.0, std_c=0.5),
            "b": SourceForecast(source="b", temp_high_c=25.0, std_c=0.5),
            "c": SourceForecast(source="c", temp_high_c=25.0, std_c=0.5),
        }
        cf = ConsensusForecast(city="NYC", date="2026-01-15", temp_high_c=25.0, std_c=0.5,
                               sources=sources, agreement_score=0.95)
        result = consensus_bucket_probability(cf, 24.0, 24.0)
        assert result > 0

    def test_low_prob_amplified(self):
        sources = {
            "a": SourceForecast(source="a", temp_high_c=30.0, std_c=0.5),
            "b": SourceForecast(source="b", temp_high_c=30.0, std_c=0.5),
            "c": SourceForecast(source="c", temp_high_c=30.0, std_c=0.5),
        }
        cf = ConsensusForecast(city="NYC", date="2026-01-15", temp_high_c=30.0, std_c=0.5,
                               sources=sources, agreement_score=0.9)
        result = consensus_bucket_probability(cf, 20.0, 20.0)
        assert 0 <= result <= 1


class TestFetchAllSources:
    @pytest.mark.asyncio
    async def test_no_sources(self):
        client = AsyncMock()
        result = await fetch_all_sources(client, "UnknownCity", "2026-01-15", {})
        assert result.city == "UnknownCity"
        assert len(result.sources) == 0

    @pytest.mark.asyncio
    async def test_with_open_meteo(self):
        from pm_bot.models.market import ForecastResult
        client = AsyncMock()
        fc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                            temp_high_c=25.0, members=[24.0, 25.0, 26.0])
        with patch("pm_bot.core.aggregation.fetch_nws_forecast", new_callable=AsyncMock, return_value=None):
            with patch("pm_bot.core.aggregation.get_icao_for_city", return_value=None):
                result = await fetch_all_sources(client, "New York", "2026-01-15", {}, fc)
        assert "open_meteo" in result.sources

    @pytest.mark.asyncio
    async def test_with_nws_and_metar(self):
        from pm_bot.models.market import ForecastResult
        client = AsyncMock()
        fc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                            temp_high_c=25.0, members=[24.0, 25.0, 26.0])
        nws_data = {"temp_high_c": 26.0, "std_c": 2.0}
        metar_data = {"temp_c": 24.0}
        with patch("pm_bot.core.aggregation.fetch_nws_forecast", new_callable=AsyncMock, return_value=nws_data):
            with patch("pm_bot.core.aggregation.get_icao_for_city", return_value="KJFK"):
                with patch("pm_bot.core.aggregation.fetch_metar", new_callable=AsyncMock, return_value=metar_data):
                    result = await fetch_all_sources(client, "New York", "2026-01-15", {}, fc)
        assert len(result.sources) == 3

    @pytest.mark.asyncio
    async def test_nws_failure(self):
        from pm_bot.models.market import ForecastResult
        client = AsyncMock()
        fc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                            temp_high_c=25.0, members=[24.0, 25.0, 26.0])
        with patch("pm_bot.core.aggregation.fetch_nws_forecast", new_callable=AsyncMock, side_effect=Exception("fail")):
            with patch("pm_bot.core.aggregation.get_icao_for_city", return_value=None):
                result = await fetch_all_sources(client, "New York", "2026-01-15", {}, fc)
        assert "open_meteo" in result.sources

    @pytest.mark.asyncio
    async def test_metar_failure(self):
        from pm_bot.models.market import ForecastResult
        client = AsyncMock()
        fc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                            temp_high_c=25.0, members=[24.0, 25.0, 26.0])
        with patch("pm_bot.core.aggregation.fetch_nws_forecast", new_callable=AsyncMock, return_value=None):
            with patch("pm_bot.core.aggregation.get_icao_for_city", return_value="KJFK"):
                with patch("pm_bot.core.aggregation.fetch_metar", new_callable=AsyncMock, side_effect=Exception("fail")):
                    result = await fetch_all_sources(client, "New York", "2026-01-15", {}, fc)
        assert "open_meteo" in result.sources

    @pytest.mark.asyncio
    async def test_no_metar_icao(self):
        from pm_bot.models.market import ForecastResult
        client = AsyncMock()
        fc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                            temp_high_c=25.0, members=[24.0, 25.0, 26.0])
        with patch("pm_bot.core.aggregation.fetch_nws_forecast", new_callable=AsyncMock, return_value=None):
            with patch("pm_bot.core.aggregation.get_icao_for_city", return_value=None):
                result = await fetch_all_sources(client, "New York", "2026-01-15", {}, fc)
        assert "open_meteo" in result.sources
        assert "metar" not in result.sources
