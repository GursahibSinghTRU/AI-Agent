"""
weather.py — Weather query detection and Environment Canada link resolution.

Detects when a user is asking about weather or conditions for a city, resolves
coordinates via the OpenStreetMap Nominatim geocoding API, and builds a direct
link to the Environment Canada weather page for that location.

Detection covers three scenarios:
  1. Direct ask — "weather in Kamloops", "Sun Peaks weather"
  2. Implicit ask — "I'm going to Sun Peaks, what are the conditions?"
     (location in current message + weather-intent words anywhere in message)
  3. History fallback — "can you check the conditions?" with no city mentioned,
     but a location was referenced in recent chat history
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

import httpx

log = logging.getLogger("weather")

# Nominatim public API — User-Agent required by usage policy
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_HEADERS = {"User-Agent": "TRU-RiskSafety-Assistant/1.0"}

# ── Intent detection ──────────────────────────────────────────────────────────

# Words that signal the user is asking about weather/conditions
_WEATHER_INTENT_WORDS = {
    "weather", "forecast", "conditions", "condition", "temperature",
    "rain", "snow", "wind", "storm", "cold", "hot", "sunny", "cloudy",
    "precipitation", "humidity", "visibility", "avalanche", "icy", "ice",
    "blizzard", "freezing", "freeze", "warming", "alert", "advisory",
}

def _has_weather_intent(text: str) -> bool:
    """Return True if the text contains any weather-related intent word."""
    lower = text.lower()
    return any(word in lower for word in _WEATHER_INTENT_WORDS)


# ── City extraction from current message ─────────────────────────────────────

# Patterns tried in order; first non-stop-word match wins.
_WEATHER_PATTERNS = [
    # "weather in/for/at/near/around Kamloops"
    re.compile(
        r"\bweather\s+(?:like\s+)?(?:in|for|at|near|around)\s+([a-zA-Z][a-zA-Z\s\-]{1,40}?)(?:\?|\.|\s*$)",
        re.IGNORECASE,
    ),
    # "Kamloops weather"
    re.compile(
        r"\b([a-zA-Z][a-zA-Z\s\-]{1,40}?)\s+weather\b",
        re.IGNORECASE,
    ),
    # "conditions in/at/for/near/around Sun Peaks"
    re.compile(
        r"\bconditions?\s+(?:in|for|at|near|around)\s+([a-zA-Z][a-zA-Z\s\-]{1,40}?)(?:\?|\.|\s*$)",
        re.IGNORECASE,
    ),
    # "current conditions at Sun Peaks" / "current forecast for Kamloops"
    re.compile(
        r"\bcurrent\s+(?:conditions?|forecast|weather)\s+(?:in|for|at|near|around)\s+([a-zA-Z][a-zA-Z\s\-]{1,40}?)(?:\?|\.|\s*$)",
        re.IGNORECASE,
    ),
    # "going/heading/travelling to Sun Peaks" — only used when weather intent is present
    re.compile(
        r"\b(?:going|heading|travelling|traveling|visiting)\s+to\s+([A-Z][a-zA-Z\s\-]{1,40}?)(?:\?|,|\.|\s+(?:can|could|will|and|do|does|to)\b)",
    ),
    # "I'm going to Sun Peaks" variant without strict punctuation terminator
    re.compile(
        r"\bgoing\s+to\s+([A-Z][a-zA-Z\s\-]{1,30}?)\s*,",
    ),
]

# Words that would produce false positives if captured as a city name
_STOP_WORDS = {
    "the", "current", "today", "outside", "local", "forecast",
    "tomorrow", "weekly", "hourly", "now", "right now", "check",
    "tell", "know", "find", "get", "see", "look", "ask",
}

# Common verb phrases that "going to X" might incorrectly capture
_VERB_FRAGMENTS = {
    "be", "go", "do", "get", "see", "check", "find", "look", "ask",
    "tell", "know", "help", "use", "try", "make", "take", "give",
    "have", "need", "want", "say", "call", "show", "stay",
}


def _is_valid_city(name: str) -> bool:
    first_word = name.split()[0].lower()
    return (
        name.lower() not in _STOP_WORDS
        and first_word not in _VERB_FRAGMENTS
        and len(name) >= 2
    )


def detect_weather_city(question: str) -> Optional[str]:
    """
    Return the city name if the question directly names a location in a
    weather/conditions context, else None.

    The last two patterns (going/heading to X) are only applied when the
    message also contains a weather-intent word, to avoid false positives.
    """
    has_intent = _has_weather_intent(question)
    for i, pattern in enumerate(_WEATHER_PATTERNS):
        # The movement patterns (indices 4, 5) require weather intent elsewhere
        if i >= 4 and not has_intent:
            continue
        m = pattern.search(question)
        if m:
            city = m.group(1).strip().rstrip("?,. ")
            if _is_valid_city(city):
                return city
    return None


# ── City extraction from chat history ────────────────────────────────────────

# Broader patterns used only when scanning history for a previously named place
_HISTORY_LOCATION_PATTERNS = [
    # "going to Sun Peaks", "heading to Sun Peaks"
    re.compile(
        r"\b(?:going|heading|travelling|traveling|visiting)\s+to\s+([A-Z][a-zA-Z\s\-]{1,40}?)(?:\?|,|\.|\s|$)",
    ),
    # "at Sun Peaks", "in Sun Peaks", "near Sun Peaks"
    re.compile(
        r"\b(?:at|in|near|around)\s+([A-Z][a-zA-Z][a-zA-Z\s\-]{1,38}?)(?:\?|,|\.|\s*$)",
    ),
    # "ski at/in Sun Peaks", "skiing at Sun Peaks"
    re.compile(
        r"\bski(?:ing)?\s+(?:at|in|near|around)\s+([A-Z][a-zA-Z\s\-]{1,40}?)(?:\?|,|\.|\s*$)",
    ),
]


def detect_city_from_history(chat_history: List[Dict[str, str]]) -> Optional[str]:
    """
    Scan recent user messages in chat history (most recent first) for a
    location that could be resolved to a weather link.
    """
    user_messages = [
        m.get("content", "")
        for m in reversed(chat_history)
        if m.get("role") == "user"
    ]
    for msg in user_messages[:6]:  # check up to 6 recent user turns
        for pattern in _HISTORY_LOCATION_PATTERNS:
            m = pattern.search(msg)
            if m:
                city = m.group(1).strip().rstrip("?,. ")
                if _is_valid_city(city):
                    return city
    return None


# ── Geocoding ─────────────────────────────────────────────────────────────────

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


# ── Public entry point ────────────────────────────────────────────────────────

def resolve_weather_link(
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Optional[str]:
    """
    Full pipeline: detect city → geocode → build URL.

    City detection order:
      1. Direct match in the current question (explicit weather/conditions ask)
      2. Implicit match in current question (movement phrase + weather intent)
      3. History fallback: current message has weather intent but no city →
         scan recent chat history for a previously mentioned location

    Returns the Environment Canada weather URL, or None if no city can be
    resolved or geocoding fails.
    """
    city = detect_weather_city(question)

    if not city and _has_weather_intent(question) and chat_history:
        city = detect_city_from_history(chat_history)

    if not city:
        return None

    coords = get_coordinates(city)
    if not coords:
        log.info("Could not resolve coordinates for city: %r", city)
        return None

    url = build_weather_url(*coords)
    log.info("Resolved weather link for %r → %s", city, url)
    return url
