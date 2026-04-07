"""
weather.py — Weather query detection and Environment Canada link resolution.

Detects when a user is asking about weather for a city, resolves coordinates
via the OpenStreetMap Nominatim geocoding API, and builds a direct link to
the Environment Canada weather page for that location.
"""

import logging
import re
from typing import Optional, Tuple

import httpx

log = logging.getLogger("weather")

# Nominatim public API — User-Agent required by usage policy
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_HEADERS = {"User-Agent": "TRU-RiskSafety-Assistant/1.0"}

# Patterns to detect a weather intent and capture the city name.
# Tried in order; first match wins.
_WEATHER_PATTERNS = [
    # "weather in Kamloops", "weather for Kamloops", "weather near Kamloops"
    re.compile(
        r"\bweather\s+(?:in|for|at|near|around)\s+([a-zA-Z][a-zA-Z\s\-]{1,40}?)(?:\?|\.|\s*$)",
        re.IGNORECASE,
    ),
    # "what is the weather in Kamloops", "what's the weather like in Kamloops"
    re.compile(
        r"\bweather\s+(?:like\s+)?(?:in|for|at|near|around)\s+([a-zA-Z][a-zA-Z\s\-]{1,40}?)(?:\?|\.|\s*$)",
        re.IGNORECASE,
    ),
    # "Kamloops weather"
    re.compile(
        r"\b([a-zA-Z][a-zA-Z\s\-]{1,40}?)\s+weather\b",
        re.IGNORECASE,
    ),
]

# Words that would produce false positives if captured as a city name
_STOP_WORDS = {
    "the", "current", "today", "outside", "local", "forecast",
    "tomorrow", "weekly", "hourly", "now", "right now",
}


def detect_weather_city(question: str) -> Optional[str]:
    """
    Return the city name if the question is asking about weather, else None.
    """
    for pattern in _WEATHER_PATTERNS:
        m = pattern.search(question)
        if m:
            city = m.group(1).strip().rstrip("?,.")
            if city.lower() not in _STOP_WORDS and len(city) >= 2:
                return city
    return None


def get_coordinates(city: str) -> Optional[Tuple[float, float]]:
    """
    Resolve a city name to (latitude, longitude) via Nominatim.
    Returns None if the city cannot be geocoded.
    """
    try:
        resp = httpx.get(
            _NOMINATIM_URL,
            params={"q": city, "format": "json", "limit": 1},
            headers=_NOMINATIM_HEADERS,
            timeout=5.0,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            lat = float(results[0]["lat"])
            lon = float(results[0]["lon"])
            return lat, lon
    except Exception as e:
        log.warning("Nominatim geocoding failed for %r: %s", city, e)
    return None


def build_weather_url(lat: float, lon: float) -> str:
    """Build an Environment Canada weather URL for the given coordinates."""
    return f"https://weather.gc.ca/en/location/index.html?coords={lat:.3f},{lon:.3f}"


def resolve_weather_link(question: str) -> Optional[str]:
    """
    Full pipeline: detect city → geocode → build URL.
    Returns the weather URL string, or None if the question is not weather-related
    or if geocoding fails.
    """
    city = detect_weather_city(question)
    if not city:
        return None
    coords = get_coordinates(city)
    if not coords:
        log.info("Could not resolve coordinates for city: %r", city)
        return None
    url = build_weather_url(*coords)
    log.info("Resolved weather link for %r → %s", city, url)
    return url
