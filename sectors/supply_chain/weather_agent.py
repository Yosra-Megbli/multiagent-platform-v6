"""
Weather Agent — v6.1 (Open-Meteo — Free, No API Key)
======================================================
BUG FIX: min_temp field removed — not in WeatherOutput schema.
validate_weather_output uses Pydantic — extra fields cause ValidationError.
"""

import httpx
import logging
from core.state import UniversalState
from core.circuit_breaker import get_circuit_breaker, CircuitOpenError
from core.schemas import validate_weather_output
from core.tracing import trace_agent

logger  = logging.getLogger(__name__)
breaker = get_circuit_breaker("open_meteo")

CITY_COORDS = {
    "tunis":      (36.8065, 10.1815),
    "sfax":       (34.7400, 10.7600),
    "sousse":     (35.8245, 10.6346),
    "bizerte":    (37.2744, 9.8739),
    "nabeul":     (36.4561, 10.7376),
    "dallas":     (32.7767, -96.7970),
    "paris":      (48.8566, 2.3522),
    "london":     (51.5074, -0.1278),
    "dubai":      (25.2048, 55.2708),
    "casablanca": (33.5731, -7.5898),
}

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _resolve_coords(location: str) -> tuple[float, float]:
    key = location.lower().split(",")[0].strip()
    return CITY_COORDS.get(key, CITY_COORDS["tunis"])


@trace_agent(agent_name="weather_agent", sector="supply_chain")
async def run_weather_agent(state: UniversalState) -> UniversalState:
    location = state["input_data"].get("location", "Tunis, Tunisia")
    lat, lon = _resolve_coords(location)

    try:
        async with breaker.protect():
            params = {
                "latitude":      lat,
                "longitude":     lon,
                "daily":         "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "forecast_days": 7,
                "timezone":      "auto",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(OPEN_METEO_URL, params=params)
                response.raise_for_status()
                data = response.json()

        daily     = data.get("daily", {})
        temps_max = daily.get("temperature_2m_max", [])
        precip    = daily.get("precipitation_sum", [])

        if not temps_max:
            raise ValueError("Empty weather response")

        avg_temp  = round(sum(temps_max) / len(temps_max), 1)
        max_temp  = round(max(temps_max), 1)
        rain_days = sum(1 for p in precip if p and p > 1.0)

        # validate_weather_output computes heat_wave internally
        output = validate_weather_output({
            "avg_temp":  avg_temp,
            "max_temp":  max_temp,
            "rain_days": rain_days,
            "heat_wave": max_temp > 35,
            "location":  location,
            "fallback":  False,
        })

        logger.info(
            "[WEATHER] Open-Meteo | location=%s max=%.1f°C rain_days=%d heat_wave=%s",
            location, max_temp, rain_days, output.get("heat_wave")
        )

    except (CircuitOpenError, Exception) as e:
        logger.warning("[WEATHER] Open-Meteo unreachable (%s) — fallback", str(e))
        state["errors"].append(f"WeatherAgent: {str(e)}")

        output = validate_weather_output({
            "avg_temp":  28.0,
            "max_temp":  33.0,
            "rain_days": 2,
            "heat_wave": False,
            "location":  location,
            "fallback":  True,
        })

    state["agent_outputs"]["weather_agent"] = output
    return state
