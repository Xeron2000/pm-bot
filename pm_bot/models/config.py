CITY_COORDS: dict[str, tuple[float, float]] = {
    "NYC": (40.7128, -74.006),
    "New York": (40.7128, -74.006),
    "London": (51.5074, -0.1278),
    "Hong Kong": (22.3193, 114.1694),
    "Miami": (25.7617, -80.1918),
    "Dallas": (32.7767, -96.797),
    "Atlanta": (33.749, -84.388),
    "Seoul": (37.5665, 126.978),
    "Tokyo": (35.6762, 139.6503),
    "Los Angeles": (34.0522, -118.2437),
    "Chicago": (41.8781, -87.6298),
    "Paris": (48.8566, 2.3522),
    "Shanghai": (31.2304, 121.4737),
    "Buenos Aires": (-34.6037, -58.3816),
    "Jeddah": (21.5433, 39.1728),
    "Ankara": (39.9334, 32.8597),
    "Lagos": (6.5244, 3.3792),
    "São Paulo": (-23.5505, -46.6333),
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
    "sum_arb": {"gap_min": 0.02},
    "ladder": {"edge_min": 0.08, "spread": 1.0},
}

CACHE_TTL: dict[str, int] = {
    "markets": 300,
    "prices": 30,
    "forecast": 3600,
    "tags": 86400,
}
