"""
weather.py — Weather query detection and Environment Canada link resolution.

Detects when a user is asking about weather or conditions for a location,
resolves coordinates via the OpenStreetMap Nominatim geocoding API, and builds
a direct link to the Environment Canada weather page for that location.

Detection covers three tiers, tried in order:
  1. Direct weather/conditions ask — "weather in Kamloops", "Sun Peaks weather",
     "conditions at Whistler"
  2. Activity + location — "skiing at Sun Peaks", "hiking near Revelstoke"
     (no weather intent words required — the activity verb is specific enough)
  3. History fallback — current message has weather intent but no city →
     scan recent chat history for a previously mentioned location using both
     activity patterns and general location patterns
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

import httpx

log = logging.getLogger("weather")

# Nominatim public API — User-Agent required by usage policy
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_HEADERS = {"User-Agent": "TRU-RiskSafety-Assistant/1.0"}

# ── Intent detection ───────────────────────────────────────────────────────────

_WEATHER_INTENT_WORDS = {
    "weather", "forecast", "conditions", "condition", "temperature",
    "rain", "snow", "wind", "storm", "cold", "hot", "sunny", "cloudy",
    "precipitation", "humidity", "visibility", "avalanche", "icy", "ice",
    "blizzard", "freezing", "freeze", "warming", "alert", "advisory",
}


def _has_weather_intent(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in _WEATHER_INTENT_WORDS)


# ── City extraction from current message ──────────────────────────────────────

# Outdoor activity verbs — specific enough that "verb at X" reliably implies a location
_ACTIVITY_VERB = (
    r"(?:ski(?:ing)?|snowboard(?:ing)?|hik(?:e|ing)|camp(?:ing)?|"
    r"climb(?:ing)?|trek(?:king)?|snowshoe(?:ing)?|kayak(?:ing)?|"
    r"raft(?:ing)?|mountaineer(?:ing)?|board(?:ing)?)"
)

# Location preposition group
_AT_PREP = r"(?:at|in|near|around|on|to)"

# Location capture group (lazy so the terminator drives the boundary)
_CITY = r"([a-zA-Z][a-zA-Z\s\-]{1,40}?)"

# Terminators that end a city name: punctuation, sentence-final whitespace, or EOS
_END = r"(?:\?|,|\.|\s*$)"

_WEATHER_PATTERNS = [
    # ── No intent gate (pattern is specific enough on its own) ────────────────

    # "weather in/for/at/near Kamloops"
    re.compile(
        rf"\bweather\s+(?:like\s+)?(?:in|for|at|near|around)\s+{_CITY}{_END}",
        re.IGNORECASE,
    ),
    # "Kamloops weather"
    re.compile(
        rf"\b{_CITY}\s+weather\b",
        re.IGNORECASE,
    ),
    # "conditions in/at/for/near Sun Peaks"
    re.compile(
        rf"\bconditions?\s+(?:in|for|at|near|around)\s+{_CITY}{_END}",
        re.IGNORECASE,
    ),
    # "current conditions/forecast/weather at Sun Peaks"
    re.compile(
        rf"\bcurrent\s+(?:conditions?|forecast|weather)\s+(?:in|for|at|near|around)\s+{_CITY}{_END}",
        re.IGNORECASE,
    ),
    # "skiing at Sun Peaks", "hiking near Whistler", "snowboarding in Revelstoke"
    # Activity verb is specific enough — no intent gate needed
    re.compile(
        rf"\b{_ACTIVITY_VERB}\s+{_AT_PREP}\s+{_CITY}{_END}",
        re.IGNORECASE,
    ),

    # ── Intent gate required (too broad without it) ───────────────────────────

    # "going/heading/travelling to Sun Peaks"
    re.compile(
        rf"\b(?:going|heading|travelling|traveling|visiting)\s+to\s+{_CITY}"
        rf"(?:\?|,|\.|\s+(?:can|could|will|and|do|does|to)\b)",
        re.IGNORECASE,
    ),
    # "going to Sun Peaks," — comma-terminated variant
    re.compile(
        r"\bgoing\s+to\s+([a-zA-Z][a-zA-Z\s\-]{1,30}?)\s*,",
        re.IGNORECASE,
    ),
]

# Indices of patterns that require a weather-intent word elsewhere in the message
_INTENT_GATED = {5, 6}

# Words/fragments that would produce false positives as a city name
_STOP_WORDS = {
    "the", "current", "today", "outside", "local", "forecast",
    "tomorrow", "weekly", "hourly", "now", "right now", "check",
    "tell", "know", "find", "get", "see", "look", "ask",
}

_VERB_FRAGMENTS = {
    "be", "go", "do", "get", "see", "check", "find", "look", "ask",
    "tell", "know", "help", "use", "try", "make", "take", "give",
    "have", "need", "want", "say", "call", "show", "stay", "work",
    "start", "stop", "run", "return", "leave", "come", "become",
    "bring", "keep", "let", "put", "set", "turn", "move", "play",
    "add", "buy", "rent", "hike", "swim", "camp", "climb",
    "this", "that", "which", "some", "any", "all", "least", "most",
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
    Return the city name if the current question names a location in a
    weather, conditions, or outdoor-activity context. Returns None otherwise.
    """
    has_intent = _has_weather_intent(question)
    for i, pattern in enumerate(_WEATHER_PATTERNS):
        if i in _INTENT_GATED and not has_intent:
            continue
        m = pattern.search(question)
        if m:
            city = m.group(1).strip().rstrip("?,. ")
            if _is_valid_city(city):
                log.debug("Detected city %r via pattern %d", city, i)
                return city
    return None


# ── City extraction from chat history ─────────────────────────────────────────

# History patterns are ordered most-specific to least-specific to avoid
# capturing common preposition phrases that aren't locations.
_HISTORY_LOCATION_PATTERNS = [
    # "skiing at sun peaks", "hiking in whistler" (most specific)
    re.compile(
        rf"\b{_ACTIVITY_VERB}\s+{_AT_PREP}\s+{_CITY}{_END}",
        re.IGNORECASE,
    ),
    # "going/heading/visiting to sun peaks"
    re.compile(
        rf"\b(?:going|heading|travelling|traveling|visiting)\s+to\s+{_CITY}{_END}",
        re.IGNORECASE,
    ),
    # "at sun peaks", "in sun peaks", "near sun peaks" (broadest — tried last)
    re.compile(
        r"\b(?:at|in|near|around)\s+([a-zA-Z]{2}[a-zA-Z\s\-]{1,38}?)(?:\?|,|\.|\s*$)",
        re.IGNORECASE,
    ),
]


def detect_city_from_history(chat_history: List[Dict[str, str]]) -> Optional[str]:
    """
    Scan recent user messages in chat history (most recent first) for a
    previously mentioned location. Returns the first valid city found.
    """
    user_messages = [
        entry.get("content", "")
        for entry in reversed(chat_history)
        if entry.get("role") == "user"
    ]
    for msg in user_messages[:6]:
        for pattern in _HISTORY_LOCATION_PATTERNS:
            match = pattern.search(msg)
            if match:
                city = match.group(1).strip().rstrip("?,. ")
                if _is_valid_city(city):
                    log.debug("Found city %r in history: %r", city, msg[:60])
                    return city
    return None


# ── Geocoding ──────────────────────────────────────────────────────────────────

def get_coordinates(city: str) -> Optional[Tuple[float, float]]:
    """Resolve a city name to (lat, lon) via Nominatim. Returns None on failure."""
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
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        log.warning("Nominatim geocoding failed for %r: %s", city, e)
    return None


def build_weather_url(lat: float, lon: float) -> str:
    return f"https://weather.gc.ca/en/location/index.html?coords={lat:.3f},{lon:.3f}"


# ── Public entry point ─────────────────────────────────────────────────────────

def resolve_weather_link(
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Optional[str]:
    """
    Full pipeline: detect city → geocode → build URL.

    Detection order:
      1. Direct or activity-based match in current question (no intent gate)
      2. Movement phrase in current question (intent gate: needs weather word)
      3. History fallback: question has weather intent but no city → scan history

    Returns the Environment Canada weather URL string, or None.
    """
    city = detect_weather_city(question)

    if not city and _has_weather_intent(question) and chat_history:
        city = detect_city_from_history(chat_history)

    if not city:
        return None

    coords = get_coordinates(city)
    if not coords:
        log.info("Could not geocode city: %r", city)
        return None

    url = build_weather_url(*coords)
    log.info("Weather link for %r → %s", city, url)
    return url
