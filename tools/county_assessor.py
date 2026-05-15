"""
County assessor & town hall property record lookup — 100% free, no API key.

Strategy (tries in order):
  1. Vision Government Solutions (gis.vgsi.com) — covers ~1,000 NE/mid-Atlantic towns
  2. Patriot Properties (patriotproperties.com) — covers MA, NH, RI towns
  3. Google Custom Search targeting *.gov / assessor / townhall sites (needs GOOGLE_CSE_ID)
  4. Returns None gracefully if nothing found

Returns: {"owner_name", "owner_address", "property_class", "source"}
"""

import re
import time
import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
}

# ── Vision GIS portal registry ─────────────────────────────────────────────────
# Format: "city, state_abbr" → subdomain (e.g. "providenceri")
# Auto-generated from known patterns: {city}{state_abbr} (lowercase, no spaces)
def _vision_subdomain(city: str, state: str) -> str:
    return re.sub(r"[^a-z0-9]", "", f"{city}{state}".lower())


def _try_vision_gis(address: str, city: str, state: str) -> dict | None:
    """
    Query Vision GIS CAMA system.
    Used by RI, MA, NH, CT, ME, VT, NY municipalities.
    API: GET https://gis.vgsi.com/{subdomain}/api/Search/ByAddress?q={query}
    """
    sub = _vision_subdomain(city, state)
    # Extract just the street address (no city/state/zip)
    street = address.split(",")[0].strip()

    url = f"https://gis.vgsi.com/{sub}/api/Search/ByAddress"
    try:
        r = requests.get(
            url,
            params={"q": street},
            headers=_HEADERS,
            timeout=8,
        )
        if r.status_code != 200:
            return None

        data = r.json()
        # Vision GIS returns a list of parcels
        parcels = data if isinstance(data, list) else data.get("Value", [])
        if not parcels:
            return None

        parcel = parcels[0]
        owner = (
            parcel.get("OwnerName") or
            parcel.get("owner_name") or
            parcel.get("Owner") or ""
        ).strip()
        mail_addr = (
            parcel.get("MailingAddress") or
            parcel.get("mailing_address") or ""
        ).strip()
        prop_class = str(parcel.get("UseCode") or parcel.get("use_code") or "").strip()

        if not owner:
            return None

        return {
            "owner_name":    owner,
            "owner_address": mail_addr or None,
            "property_class": prop_class or None,
            "source":        f"Vision GIS ({sub})",
        }
    except Exception:
        return None


# ── Patriot Properties portal ──────────────────────────────────────────────────
def _patriot_subdomain(city: str, state: str) -> str:
    return re.sub(r"[^a-z0-9]", "", f"{city}{state}".lower())


def _try_patriot_properties(address: str, city: str, state: str) -> dict | None:
    """
    Query Patriot Properties CAMA system.
    URL: https://patriotproperties.com/{sub}/search.asp
    """
    sub = _patriot_subdomain(city, state)
    street = address.split(",")[0].strip()

    # Patriot uses a POST form-based search
    url = f"https://patriotproperties.com/{sub}/search.asp"
    try:
        r = requests.post(
            url,
            data={
                "TaxParcelSearch": "1",
                "AddressSearch":   "1",
                "Address":         street,
            },
            headers=_HEADERS,
            timeout=8,
        )
        if r.status_code != 200 or "no records" in r.text.lower():
            return None

        # Parse owner from HTML table
        owner_match = re.search(
            r'Owner[^>]*>\s*<td[^>]*>\s*([A-Z][A-Z ,&]+)\s*</td>',
            r.text, re.IGNORECASE
        )
        if not owner_match:
            return None

        owner = owner_match.group(1).strip().title()
        return {
            "owner_name":    owner,
            "owner_address": None,
            "property_class": None,
            "source":        f"Patriot Properties ({sub})",
        }
    except Exception:
        return None


# ── Google Custom Search targeting assessor/gov sites ─────────────────────────
def _try_google_assessor(
    address: str, city: str, state: str,
    api_key: str, cse_id: str,
) -> dict | None:
    """
    Search Google for assessor/town-hall records for the address.
    Uses targeted query to surface government property record pages.
    """
    if not api_key or not cse_id:
        return None

    street = address.split(",")[0].strip()
    query  = (
        f'"{street}" "{city}" "{state}" owner '
        f'(assessor OR "property records" OR "town hall" OR parcel OR taxpayer)'
    )

    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cse_id, "q": query, "num": 5},
            timeout=8,
        )
        if r.status_code != 200:
            return None

        items = r.json().get("items", [])
        for item in items:
            text = f"{item.get('title','')} {item.get('snippet','')}"
            # Look for "Owner: JOHN SMITH" or "Taxpayer: JANE DOE" patterns
            m = re.search(
                r'(?:owner|taxpayer|assessed to)[:\s]+([A-Z][A-Z\s,\.]{4,40})',
                text, re.IGNORECASE
            )
            if m:
                name = m.group(1).strip().title()
                # Filter noise
                if len(name.split()) >= 2 and not any(
                    w in name.lower() for w in
                    ("search", "result", "record", "parcel", "property", "address", "county")
                ):
                    return {
                        "owner_name":    name,
                        "owner_address": None,
                        "property_class": None,
                        "source":        f"Assessor (Google → {item.get('displayLink','')})",
                    }
    except Exception:
        pass
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def lookup_assessor(
    address:  str,
    api_key:  str = None,
    cse_id:   str = None,
) -> dict:
    """
    Look up property owner from county assessor / town hall records.
    Tries multiple sources; returns first successful result.
    All keys: owner_name, owner_address, property_class, source (may be None).
    """
    empty = {"owner_name": None, "owner_address": None, "property_class": None, "source": None}

    # Parse city and state from address
    # Supports: "123 Main St, Providence, RI, 02905 ..." or "123 Main St, Providence, RI"
    parts = [p.strip() for p in address.split(",")]
    if len(parts) < 3:
        return empty

    city  = parts[-3] if len(parts) >= 3 else parts[0]
    state = re.sub(r"[^A-Za-z]", "", parts[-2])[:2].upper() if len(parts) >= 2 else ""

    if not city or not state:
        return empty

    # 1. Try Vision GIS
    result = _try_vision_gis(address, city, state)
    if result:
        return result

    time.sleep(0.3)

    # 2. Try Patriot Properties
    result = _try_patriot_properties(address, city, state)
    if result:
        return result

    time.sleep(0.3)

    # 3. Try Google Custom Search targeting assessor/gov sites
    result = _try_google_assessor(address, city, state, api_key, cse_id)
    if result:
        return result

    return empty


def enrich_with_assessor(
    leads: list[dict],
    api_key: str = None,
    cse_id:  str = None,
    max_lookups: int = 10,
) -> list[dict]:
    """Enrich residential leads with assessor owner data (in-place)."""
    enriched = []
    count = 0
    for lead in leads:
        if count < max_lookups and lead.get("lead_type") in ("for_sale", "recently_sold"):
            rec = lookup_assessor(lead["address"], api_key, cse_id)
            if rec.get("owner_name"):
                lead = {
                    **lead,
                    "owner_name":    rec["owner_name"],
                    "owner_address": rec.get("owner_address"),
                    "owner_source":  rec.get("source"),
                }
            count += 1
        enriched.append(lead)
    return enriched
