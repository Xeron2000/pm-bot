CITY_COORDS: dict[str, tuple[float, float]] = {
    "NYC": (40.7772, -73.8726),
    "New York": (40.7772, -73.8726),
    "London": (51.5048, 0.0495),
    "Hong Kong": (22.3080, 113.9185),
    "Miami": (25.7953, -80.2902),
    "Dallas": (32.8471, -96.8518),
    "Atlanta": (33.6407, -84.4277),
    "Seoul": (37.4602, 126.4407),
    "Tokyo": (35.5522, 139.7796),
    "Los Angeles": (33.9425, -118.4081),
    "Chicago": (41.9742, -87.9073),
    "Paris": (48.9694, 2.4414),
    "Shanghai": (31.1443, 121.8083),
    "Buenos Aires": (-34.8222, -58.5358),
    "Jeddah": (21.6796, 39.1565),
    "Ankara": (40.1281, 32.9951),
    "Lagos": (6.5774, 3.3210),
    "São Paulo": (-23.4356, -46.4731),
    "Warsaw": (52.1657, 20.9671),
    "Taipei": (25.0796, 121.2340),
    "Austin": (30.1945, -97.6699),
    "Helsinki": (60.3172, 24.9635),
    "Denver": (39.8617, -104.6732),
}

CITY_ALIASES: dict[str, str] = {
    "NYC": "New York",
    "LA": "Los Angeles",
    "HK": "Hong Kong",
    "SP": "São Paulo",
    "SAO": "São Paulo",
    "BSAS": "Buenos Aires",
    "BA": "Buenos Aires",
}


def resolve_city_alias(name: str) -> str:
    return CITY_ALIASES.get(name, name)


DEFAULT_CITIES = ["NYC", "London", "Hong Kong", "Miami", "Dallas", "Atlanta", "Seoul", "Tokyo"]

STRATEGY_DEFAULTS: dict[str, dict[str, float]] = {
    "gopfan2": {"yes_max": 0.15, "no_min": 0.45},
    "narrow_no": {"max_bucket_width_c": 2.0, "no_min": 0.45},
    "resolution_div": {"bankroll": 100.0},
    "neg_risk_sum": {"bankroll": 100.0},
    "truncation_edge": {"edge_min": 0.03},
    "ensemble_spread": {"edge_min": 0.05},
}

CACHE_TTL: dict[str, int] = {
    "markets": 300,
    "prices": 30,
    "forecast": 3600,
    "tags": 86400,
}
