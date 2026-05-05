from __future__ import annotations


from pm_bot.cli.display import render_recommendations, render_verbose, render_events
from pm_bot.models.market import Recommendation, WeatherEvent, TemperatureBucket


def _make_bucket(**kw):
    defaults = dict(market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                    temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0)
    defaults.update(kw)
    return TemperatureBucket(**defaults)


def _make_event(**kw):
    defaults = dict(event_id="ev1", title="Test", slug="test", city="New York",
                    date="2026-01-15", measure_type="high",
                    buckets=[_make_bucket()])
    defaults.update(kw)
    return WeatherEvent(**defaults)


def _make_rec(**kw):
    ev = _make_event()
    defaults = dict(strategy="gopfan2", event=ev, bucket=ev.buckets[0],
                    direction="YES", edge=0.15, reasoning="test reason")
    defaults.update(kw)
    return Recommendation(**defaults)


class TestRenderRecommendations:
    def test_empty(self):
        render_recommendations([])

    def test_single_rec(self):
        rec = _make_rec()
        render_recommendations([rec])

    def test_multiple_sorted(self):
        recs = [_make_rec(edge=0.05), _make_rec(edge=0.15), _make_rec(edge=0.10)]
        render_recommendations(recs)

    def test_direction_yes(self):
        rec = _make_rec(direction="YES", edge=0.15)
        render_recommendations([rec])

    def test_direction_no(self):
        rec = _make_rec(direction="NO", edge=0.10)
        render_recommendations([rec])

    def test_low_edge(self):
        rec = _make_rec(edge=0.03)
        render_recommendations([rec])

    def test_high_edge(self):
        rec = _make_rec(edge=0.25)
        render_recommendations([rec])

    def test_long_reasoning(self):
        rec = _make_rec(reasoning="x" * 100)
        render_recommendations([rec])


class TestRenderVerbose:
    def test_empty(self):
        render_verbose([])

    def test_single_rec(self):
        rec = _make_rec()
        render_verbose([rec])

    def test_multiple(self):
        recs = [_make_rec(edge=0.05), _make_rec(edge=0.15)]
        render_verbose(recs)


class TestRenderEvents:
    def test_empty(self):
        render_events([])

    def test_single_event(self):
        ev = _make_event()
        render_events([ev])

    def test_multiple_events(self):
        ev1 = _make_event(city="New York")
        ev2 = _make_event(city="London", event_id="ev2")
        render_events([ev1, ev2])

    def test_airport_code(self):
        ev = _make_event(airport_code="KLGA")
        render_events([ev])

    def test_no_airport_code(self):
        ev = _make_event()
        render_events([ev])

    def test_large_gap(self):
        bucket = _make_bucket(yes_price=0.60, no_price=0.60)
        ev = _make_event(buckets=[bucket])
        render_events([ev])
