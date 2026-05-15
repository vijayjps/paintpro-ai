"""
Web intelligence layer — searches all online sources for painting leads.
Covers: Zillow, Redfin, Trulia, Homes.com, foreclosures/HUD/auction,
        Craigslist, apartment complexes, commercial buildings (malls, offices),
        Facebook Marketplace ads, blogs, and local news.
All results pre-fetched and injected as agent context (no LLM tool-call needed).
"""

import re
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ── DuckDuckGo helper ─────────────────────────────────────────────────────────

def _ddg(query: str, max_results: int = 8) -> list[dict]:
    try:
        from ddgs import DDGS
        return list(DDGS().text(query, max_results=max_results)) or []
    except Exception:
        return []


def _extract_listing(r: dict, source: str, city: str, state: str) -> dict | None:
    """Parse a DDG result into a structured listing, filtering wrong cities."""
    url     = r.get("href", "")
    title   = r.get("title", "")
    snippet = r.get("body", "")
    combined = (title + " " + snippet).lower()
    if city.lower() not in combined and state.upper().lower() not in combined:
        return None
    yr_match    = re.search(r'[Bb]uilt\s+(?:in\s+)?(\d{4})', snippet)
    price_match = re.search(r'\$[\d,]+', snippet + title)
    return {
        "source":     source,
        "title":      title,
        "snippet":    snippet[:200],
        "url":        url,
        "year_built": int(yr_match.group(1))    if yr_match    else None,
        "price":      price_match.group(0)       if price_match else "",
    }


# ── Residential listing sites ─────────────────────────────────────────────────

def search_zillow(city: str, state: str) -> list[dict]:
    queries = [
        f'site:zillow.com "{city}, {state.upper()}" for sale "built in 19"',
        f'site:zillow.com "{city}, {state.upper()}" for sale fixer OR "TLC" OR "needs work"',
        f'site:zillow.com/homes/for_sale/{city.replace(" ", "-")}-{state.upper()}',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 8):
            if "zillow.com" not in r.get("href", "") or r["href"] in seen:
                continue
            item = _extract_listing(r, "Zillow", city, state)
            if item:
                seen.add(r["href"])
                out.append(item)
        if len(out) >= 8:
            break
    return out[:8]


def search_redfin(city: str, state: str) -> list[dict]:
    queries = [
        f'site:redfin.com "{city}, {state.upper()}" for sale "built in 19" OR "1950s" OR "1960s" OR "1970s"',
        f'site:redfin.com "{city}, {state.upper()}" for sale fixer OR "as-is" OR "TLC"',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 6):
            if "redfin.com" not in r.get("href", "") or r["href"] in seen:
                continue
            item = _extract_listing(r, "Redfin", city, state)
            if item:
                seen.add(r["href"])
                out.append(item)
        if len(out) >= 8:
            break
    return out[:8]


def search_trulia(city: str, state: str) -> list[dict]:
    queries = [
        f'site:trulia.com "{city}, {state.upper()}" for sale fixer OR old OR historic OR "price reduced"',
        f'site:trulia.com/homes/for_sale/{state.upper()}/{city.replace(" ", "_")}',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 5):
            if "trulia.com" not in r.get("href", "") or r["href"] in seen:
                continue
            item = _extract_listing(r, "Trulia", city, state)
            if item:
                seen.add(r["href"])
                out.append(item)
        if len(out) >= 6:
            break
    return out[:6]


def search_homes_com(city: str, state: str) -> list[dict]:
    """Homes.com — large listing aggregator not covered by homeharvest."""
    queries = [
        f'site:homes.com "{city}, {state.upper()}" for sale "built" old OR fixer OR historic',
        f'site:homes.com/homes-for-sale/{city.replace(" ", "-").lower()}-{state.lower()}',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 6):
            if "homes.com" not in r.get("href", "") or r["href"] in seen:
                continue
            item = _extract_listing(r, "Homes.com", city, state)
            if item:
                seen.add(r["href"])
                out.append(item)
        if len(out) >= 6:
            break
    return out[:6]


# ── Foreclosures & distressed ─────────────────────────────────────────────────

def search_foreclosures(city: str, state: str) -> list[dict]:
    """HUD homes, bank-owned, auction, and tax-delinquent properties."""
    queries = [
        f'site:hudhomestore.gov "{city}" "{state.upper()}" for sale',
        f'site:auction.com "{city}, {state.upper()}" foreclosure OR bank-owned',
        f'site:foreclosure.com "{city}" "{state.upper()}"',
        f'"{city}, {state.upper()}" bank-owned OR foreclosure OR "REO" OR "HUD home" for sale exterior',
        f'"{city} {state.upper()}" tax delinquent OR "tax lien" home for sale',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 5):
            url = r.get("href", "")
            if url in seen:
                continue
            title   = r.get("title", "")
            snippet = r.get("body", "")
            seen.add(url)
            out.append({
                "source":  "Foreclosure/HUD",
                "title":   title,
                "snippet": snippet[:200],
                "url":     url,
            })
        if len(out) >= 10:
            break
    return out[:10]


# ── Apartment complexes ───────────────────────────────────────────────────────

def search_apartments(city: str, state: str) -> list[dict]:
    """
    Apartment complexes and multi-family buildings — large exterior surfaces,
    property managers often hire commercial painters for full building repaints.
    """
    queries = [
        f'"{city}, {state.upper()}" apartment complex exterior painting OR repaint OR renovation',
        f'site:apartments.com "{city}, {state.upper()}" complex built 19 OR older',
        f'site:apartmentlist.com "{city}" "{state.upper()}" apartment community',
        f'"{city} {state.upper()}" multi-family building property management exterior maintenance',
        f'"{city}" apartment complex "property manager" exterior OR facade OR siding painting',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 5):
            url = r.get("href", "")
            if url in seen:
                continue
            title   = r.get("title", "")
            snippet = r.get("body", "")
            seen.add(url)
            out.append({
                "source":  "Apartment/Multi-Family",
                "title":   title,
                "snippet": snippet[:200],
                "url":     url,
            })
        if len(out) >= 10:
            break
    return out[:10]


# ── Commercial buildings ──────────────────────────────────────────────────────

def search_commercial(city: str, state: str) -> list[dict]:
    """
    Malls, shopping centers, office parks, strip malls, warehouses.
    Commercial exteriors need repainting every 5-10 years — large contracts.
    """
    queries = [
        f'"{city}, {state.upper()}" shopping mall OR strip mall exterior painting OR repaint OR renovation',
        f'"{city} {state.upper()}" office building OR office park exterior facade painting maintenance',
        f'site:loopnet.com "{city}, {state.upper()}" commercial building for sale OR lease',
        f'"{city}" commercial property management exterior painting OR maintenance 2024 OR 2025',
        f'"{city} {state.upper()}" warehouse OR industrial building exterior repaint OR coating',
        f'"{city}" shopping center OR retail plaza property manager exterior renovation',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 5):
            url = r.get("href", "")
            if url in seen:
                continue
            title   = r.get("title", "")
            snippet = r.get("body", "")
            seen.add(url)
            out.append({
                "source":  "Commercial/Mall/Office",
                "title":   title,
                "snippet": snippet[:200],
                "url":     url,
            })
        if len(out) >= 10:
            break
    return out[:10]


# ── Ads & marketplaces ────────────────────────────────────────────────────────

def search_ads(city: str, state: str) -> list[dict]:
    queries = [
        f'site:craigslist.org "{city}" house for sale "needs paint" OR "TLC" OR "handyman" OR "fixer"',
        f'site:facebook.com/marketplace "{city} {state}" home for sale fixer OR paint OR old',
        f'"{city} {state.upper()}" house for sale "needs paint" OR "faded exterior" OR "handyman special"',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 5):
            url = r.get("href", "")
            if url not in seen:
                seen.add(url)
                out.append({
                    "source":  "Ad/Marketplace",
                    "title":   r.get("title", ""),
                    "snippet": r.get("body", "")[:150],
                    "url":     url,
                })
    return out[:8]


# ── Blogs & community ─────────────────────────────────────────────────────────

def search_blogs(city: str, state: str) -> list[dict]:
    queries = [
        f'"{city} {state.upper()}" real estate blog "exterior paint" OR "curb appeal" OR "repaint"',
        f'"{city} {state.upper()}" homes "peeling paint" OR "faded siding" OR "paint needed"',
        f'site:reddit.com "{city}" home painting OR house exterior OR curb appeal',
        f'"{city} {state.upper()}" neighborhood renovation painting 2024 OR 2025',
    ]
    seen, out = set(), []
    for q in queries:
        for r in _ddg(q, 4):
            url = r.get("href", "")
            if url not in seen:
                seen.add(url)
                out.append({
                    "source":  "Blog/Community",
                    "title":   r.get("title", ""),
                    "snippet": r.get("body", "")[:150],
                    "url":     url,
                })
    return out[:8]


# ── Craigslist direct ─────────────────────────────────────────────────────────

_CL_CITY_MAP = {
    "springfield": "springfieldil", "chicago": "chicago", "peoria": "peoria",
    "rockford": "rockford", "champaign": "chambana", "decatur": "decatur",
    "aurora": "chicago", "joliet": "chicago", "naperville": "chicago",
    "new york": "newyork", "los angeles": "losangeles", "houston": "houston",
    "phoenix": "phoenix", "philadelphia": "philadelphia", "san antonio": "sanantonio",
    "san diego": "sandiego", "dallas": "dallas", "austin": "austin",
    "jacksonville": "jacksonville", "columbus": "columbus", "charlotte": "charlotte",
    "indianapolis": "indianapolis", "denver": "denver", "seattle": "seattle",
    "boston": "boston", "nashville": "nashville", "baltimore": "baltimore",
    "portland": "portland", "las vegas": "lasvegas", "memphis": "memphis",
    "atlanta": "atlanta", "miami": "miami", "minneapolis": "minneapolis",
    "raleigh": "raleigh", "tampa": "tampa", "orlando": "orlando",
    "st louis": "stlouis", "cincinnati": "cincinnati", "milwaukee": "milwaukee",
    "cleveland": "cleveland", "pittsburgh": "pittsburgh", "sacramento": "sacramento",
    "kansas city": "kansascity", "richmond": "richmond", "tucson": "tucson",
}


def scrape_craigslist(city: str, state: str, max_listings: int = 8) -> list[dict]:
    cl_city = _CL_CITY_MAP.get(city.lower().strip(), city.lower().replace(" ", ""))
    listings, seen = [], set()
    for kw in ["needs paint", "fixer upper", "handyman special", "tlc"]:
        url = f"https://{cl_city}.craigslist.org/search/rea?query={kw.replace(' ', '+')}&sort=date"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for item in soup.select("li.cl-static-search-result, li.result-row")[:5]:
                title_el = item.select_one(".title, a.posting-title")
                price_el = item.select_one(".priceinfo, .result-price")
                link_el  = item.select_one("a")
                title = title_el.get_text(strip=True) if title_el else ""
                price = price_el.get_text(strip=True) if price_el else ""
                href  = link_el["href"] if link_el and link_el.get("href") else ""
                if title and title not in seen:
                    seen.add(title)
                    listings.append({
                        "source": "Craigslist",
                        "title":  title,
                        "price":  price,
                        "url":    href if href.startswith("http") else f"https://{cl_city}.craigslist.org{href}",
                    })
            time.sleep(0.4)
        except Exception:
            continue
        if len(listings) >= max_listings:
            break
    return listings[:max_listings]


# ── Aggregator ────────────────────────────────────────────────────────────────

def gather_web_intelligence(city: str, state: str) -> dict:
    """Run all intelligence sources in parallel and return structured results."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {
            "zillow":       ex.submit(search_zillow,       city, state),
            "redfin":       ex.submit(search_redfin,       city, state),
            "trulia":       ex.submit(search_trulia,       city, state),
            "homes_com":    ex.submit(search_homes_com,    city, state),
            "foreclosures": ex.submit(search_foreclosures, city, state),
            "apartments":   ex.submit(search_apartments,   city, state),
            "commercial":   ex.submit(search_commercial,   city, state),
            "ads":          ex.submit(search_ads,          city, state),
            "blogs":        ex.submit(search_blogs,        city, state),
            "craigslist":   ex.submit(scrape_craigslist,   city, state),
        }
    return {k: v.result() for k, v in futures.items()}


def format_web_intel_for_agent(intel: dict) -> str:
    """Format all intelligence into a readable block for the agent."""
    sections = []

    # Residential listing sites
    for key, label in [
        ("zillow",    "ZILLOW"),
        ("redfin",    "REDFIN"),
        ("trulia",    "TRULIA"),
        ("homes_com", "HOMES.COM"),
    ]:
        items = intel.get(key, [])
        if not items:
            continue
        lines = [f"--- {label} LISTINGS ---"]
        for item in items:
            yr = f" | Built {item['year_built']}" if item.get("year_built") else ""
            pr = f" | {item['price']}"            if item.get("price")      else ""
            lines.append(f"• {item['title']}{yr}{pr}")
            if item.get("snippet"):
                lines.append(f"  {item['snippet'][:120]}")
        sections.append("\n".join(lines))

    # Foreclosures
    if intel.get("foreclosures"):
        lines = ["--- FORECLOSURES / HUD / BANK-OWNED / TAX DELINQUENT ---"]
        for item in intel["foreclosures"][:8]:
            lines.append(f"• {item['title']}")
            if item.get("snippet"):
                lines.append(f"  {item['snippet'][:120]}")
        sections.append("\n".join(lines))

    # Craigslist
    if intel.get("craigslist"):
        lines = ["--- CRAIGSLIST (fixer/TLC/handyman listings) ---"]
        for item in intel["craigslist"]:
            pr = f" | {item['price']}" if item.get("price") else ""
            lines.append(f"• {item['title']}{pr}")
        sections.append("\n".join(lines))

    # Apartment complexes
    if intel.get("apartments"):
        lines = ["--- APARTMENT COMPLEXES & MULTI-FAMILY BUILDINGS ---"]
        for item in intel["apartments"][:6]:
            lines.append(f"• {item['title']}")
            if item.get("snippet"):
                lines.append(f"  {item['snippet'][:120]}")
        sections.append("\n".join(lines))

    # Commercial
    if intel.get("commercial"):
        lines = ["--- COMMERCIAL BUILDINGS (malls, offices, warehouses) ---"]
        for item in intel["commercial"][:6]:
            lines.append(f"• {item['title']}")
            if item.get("snippet"):
                lines.append(f"  {item['snippet'][:120]}")
        sections.append("\n".join(lines))

    # Ads & blogs
    for key, label in [("ads", "ADS & MARKETPLACE"), ("blogs", "BLOGS & COMMUNITY")]:
        items = intel.get(key, [])
        if not items:
            continue
        lines = [f"--- {label} ---"]
        for item in items[:5]:
            lines.append(f"• {item['title']}")
            if item.get("snippet"):
                lines.append(f"  {item['snippet'][:120]}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else ""
