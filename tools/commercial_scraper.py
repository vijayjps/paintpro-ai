"""
Commercial property data from two free sources:
  1. OpenStreetMap Overpass API  — no API key, global coverage
  2. Google Places Nearby Search — uses GOOGLE_API_KEY (already in .env)

Both return the same dict schema so crew.py can merge them transparently.
"""

import time
import requests

NOMINATIM_UA = "PaintProAI/1.0 (commercial-lead-scraper)"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _geocode(location: str) -> tuple[float, float] | None:
    """City/state → (lat, lon) via Nominatim (free, no key)."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": NOMINATIM_UA},
            timeout=8,
        )
        if r.status_code == 200:
            hits = r.json()
            if hits:
                return float(hits[0]["lat"]), float(hits[0]["lon"])
    except Exception:
        pass
    return None


def _score_commercial(building_type: str, name: str) -> int:
    """Score a commercial property by exterior-painting likelihood (0-100)."""
    bt = (building_type or "").lower()
    nm = (name or "").lower()
    score = 10

    # Building type signals
    high   = ("warehouse", "industrial", "factory", "storage")
    medium = ("retail", "commercial", "supermarket", "mall", "shopping", "hotel", "motel", "lodge")
    govt   = ("school", "hospital", "clinic", "government", "municipal", "church", "place_of_worship")
    office = ("office", "coworking", "business_park")

    if any(k in bt for k in high):
        score += 50
    elif any(k in bt for k in medium):
        score += 40
    elif any(k in bt for k in govt):
        score += 35
    elif any(k in bt for k in office):
        score += 30
    else:
        score += 20

    # Name keyword bonus
    for kw in ("center", "plaza", "complex", "park", "mall", "tower", "square", "village"):
        if kw in nm:
            score += 10
            break

    return min(score, 100)


# ── Source 1: OpenStreetMap Overpass API ───────────────────────────────────────

_OSM_FILTERS = "|".join([
    "commercial", "retail", "office", "warehouse", "industrial",
    "supermarket", "hotel", "motel", "school", "hospital", "church",
    "storage", "factory", "civic", "government",
])

_OSM_AMENITIES = "|".join([
    "school", "place_of_worship", "hospital", "clinic", "hotel",
    "restaurant", "fast_food", "bar", "cafe", "bank", "pharmacy",
    "cinema", "theatre", "community_centre", "public_building",
])

_OSM_SHOPS = "|".join([
    "supermarket", "mall", "department_store", "wholesale",
    "furniture", "electronics", "clothes", "hardware",
])


def fetch_osm_commercial(location: str, radius_miles: int = 10, max_results: int = 20) -> list[dict]:
    """Pull commercial properties from OpenStreetMap Overpass API."""
    coords = _geocode(location)
    if not coords:
        return []

    lat, lon  = coords
    radius_m  = int(radius_miles * 1609.34)
    city_name = location.split(",")[0].strip()

    query = f"""
[out:json][timeout:30];
(
  way["building"~"{_OSM_FILTERS}"](around:{radius_m},{lat},{lon});
  node["amenity"~"{_OSM_AMENITIES}"](around:{radius_m},{lat},{lon});
  way["amenity"~"{_OSM_AMENITIES}"](around:{radius_m},{lat},{lon});
  node["shop"~"{_OSM_SHOPS}"](around:{radius_m},{lat},{lon});
  node["office"](around:{radius_m},{lat},{lon});
  way["landuse"~"commercial|industrial|retail"](around:{radius_m},{lat},{lon});
);
out center tags {max_results * 4};
"""

    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=35)
        if r.status_code != 200:
            return []

        results, seen = [], set()

        for el in r.json().get("elements", []):
            tags = el.get("tags", {})
            name = (tags.get("name") or "").strip()
            if not name:
                continue

            # Build the best address we can
            parts = []
            if tags.get("addr:housenumber") and tags.get("addr:street"):
                parts.append(f"{tags['addr:housenumber']} {tags['addr:street']}")
            elif tags.get("addr:street"):
                parts.append(tags["addr:street"])

            parts.append(tags.get("addr:city") or city_name)
            if tags.get("addr:state"):
                parts.append(tags["addr:state"])

            address = ", ".join(filter(None, parts))
            if not address:
                address = f"{name}, {city_name}"

            key = address.lower()[:45]
            if key in seen:
                continue
            seen.add(key)

            btype = (
                tags.get("building") or tags.get("amenity") or
                tags.get("shop")     or tags.get("office")  or
                tags.get("landuse")  or "commercial"
            )

            results.append({
                "address":       address,
                "name":          name,
                "building_type": btype,
                "lead_type":     "commercial_osm",
                "score":         _score_commercial(btype, name),
            })
            if len(results) >= max_results * 2:
                break

        return sorted(results, key=lambda x: x["score"], reverse=True)[:max_results]

    except Exception:
        return []


def _get_place_phone(place_id: str, api_key: str) -> str | None:
    """Fetch phone number for a Google Place via Place Details API."""
    if not place_id or not api_key:
        return None
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={"place_id": place_id, "fields": "formatted_phone_number", "key": api_key},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json().get("result", {}).get("formatted_phone_number")
    except Exception:
        pass
    return None


# ── Source 2: Google Places Nearby Search ─────────────────────────────────────

# Types that yield high-value painting leads
_GP_TYPES = [
    "shopping_mall",
    "school",
    "place_of_worship",
    "hospital",
    "hotel",
    "restaurant",
    "gym",
    "movie_theater",
    "warehouse_store",
]


def fetch_google_places_commercial(
    location: str,
    radius_miles: int = 10,
    api_key: str = None,
    max_results: int = 20,
) -> list[dict]:
    """Pull commercial properties from Google Places Nearby Search."""
    if not api_key:
        return []

    coords = _geocode(location)
    if not coords:
        return []

    lat, lon  = coords
    radius_m  = min(int(radius_miles * 1609.34), 50_000)  # Google cap = 50 km
    city_name = location.split(",")[0].strip()

    results, seen = [], set()

    for ptype in _GP_TYPES:
        if len(results) >= max_results:
            break
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                params={
                    "location":  f"{lat},{lon}",
                    "radius":    radius_m,
                    "type":      ptype,
                    "key":       api_key,
                },
                timeout=8,
            )
            if r.status_code != 200:
                continue

            for place in r.json().get("results", [])[:6]:
                name     = (place.get("name") or "").strip()
                vicinity = (place.get("vicinity") or "").strip()
                if not name or not vicinity:
                    continue

                # Append city if not already in vicinity
                if city_name.lower() not in vicinity.lower():
                    address = f"{vicinity}, {city_name}"
                else:
                    address = vicinity

                key = address.lower()[:45]
                if key in seen:
                    continue
                seen.add(key)

                phone = _get_place_phone(place.get("place_id"), api_key)
                results.append({
                    "address":       address,
                    "name":          name,
                    "building_type": ptype.replace("_", " "),
                    "lead_type":     "commercial_google",
                    "score":         _score_commercial(ptype, name),
                    "phone":         phone,
                })

        except Exception:
            continue

        time.sleep(0.08)   # stay well within Google rate limits

    return sorted(results, key=lambda x: x["score"], reverse=True)[:max_results]


# ── Formatter ──────────────────────────────────────────────────────────────────

def format_commercial_for_agent(osm_leads: list[dict], google_leads: list[dict]) -> str:
    """Merge and format commercial leads for the prospector agent."""
    all_leads = osm_leads + google_leads
    if not all_leads:
        return ""

    # Deduplicate across sources by name similarity
    seen, unique = set(), []
    for lead in sorted(all_leads, key=lambda x: x["score"], reverse=True):
        key = lead["name"].lower()[:30]
        if key not in seen:
            seen.add(key)
            unique.append(lead)

    lines = [f"=== COMMERCIAL PROPERTIES ({len(unique)} found via OSM + Google Places) ==="]
    for i, lead in enumerate(unique, 1):
        src   = "OSM" if lead["lead_type"] == "commercial_osm" else "Google"
        btype = lead["building_type"].replace("_", " ").title()
        lines.append(f"{i}. {lead['address']}  [{lead['name']}]  — {btype}  [{src}]")

    return "\n".join(lines)
