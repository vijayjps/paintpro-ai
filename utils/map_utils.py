"""
Map utilities — geocode addresses via Nominatim (free, no API key)
and build a Folium map with colour-coded lead markers.
"""

import time
import folium
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

_geocoder = Nominatim(user_agent="paint_lead_gen_app")

# Simple in-process cache so repeat runs don't re-geocode the same address
_geocode_cache: dict[str, tuple[float, float] | None] = {}


def geocode_address(address: str) -> tuple[float, float] | None:
    if address in _geocode_cache:
        return _geocode_cache[address]
    try:
        time.sleep(1.1)  # Nominatim rate-limit: 1 req/sec
        loc = _geocoder.geocode(address, timeout=10)
        result = (loc.latitude, loc.longitude) if loc else None
    except (GeocoderTimedOut, GeocoderServiceError):
        result = None
    _geocode_cache[address] = result
    return result


def build_leads_map(leads: list[dict], center_location: str = "") -> folium.Map:
    """
    leads: list of dicts with keys: address, priority, label (optional)
    Returns a folium.Map ready to render with st_folium.
    """
    PRIORITY_COLOR = {"HOT": "red", "WARM": "orange", "COLD": "blue"}
    DEFAULT_CENTER = [39.5, -98.35]  # geographic centre of US
    DEFAULT_ZOOM   = 4

    # Try to geocode leads
    geocoded = []
    for lead in leads:
        coords = geocode_address(lead.get("address", ""))
        if coords:
            geocoded.append({**lead, "lat": coords[0], "lon": coords[1]})

    if geocoded:
        avg_lat = sum(g["lat"] for g in geocoded) / len(geocoded)
        avg_lon = sum(g["lon"] for g in geocoded) / len(geocoded)
        center  = [avg_lat, avg_lon]
        zoom    = 13
    else:
        center = DEFAULT_CENTER
        zoom   = DEFAULT_ZOOM

    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")

    for i, g in enumerate(geocoded, 1):
        priority = g.get("priority", "WARM")
        color    = PRIORITY_COLOR.get(priority, "blue")
        label    = g.get("label", g["address"])
        popup_html = (
            f"<b>Lead {i}</b><br>"
            f"{g['address']}<br>"
            f"<span style='color:{color};font-weight:bold;'>{priority}</span>"
        )
        folium.Marker(
            location=[g["lat"], g["lon"]],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"Lead {i}: {g['address'][:40]}",
            icon=folium.Icon(color=color, icon="home", prefix="fa"),
        ).add_to(m)

    # Draw route polyline if multiple points
    if len(geocoded) >= 2:
        route_coords = [[g["lat"], g["lon"]] for g in geocoded]
        folium.PolyLine(
            route_coords,
            color="gray",
            weight=1.5,
            opacity=0.5,
            tooltip="Drive order",
        ).add_to(m)

    return m
