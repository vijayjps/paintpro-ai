"""
Real property listing scraper using HomeHarvest (Realtor.com).
Fetches active listings AND recently sold homes (new owners = hottest leads).
Scores each property by likelihood of needing exterior painting.
"""

import pandas as pd


def _safe_str(val) -> str:
    """Safely convert a value (including pd.NA / NaN) to a stripped string."""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip() if val is not None else ""


def _extract_phone(phones) -> str | None:
    """Pull best phone number from HomeHarvest agent_phones / office_phones list."""
    try:
        if phones is None or pd.isna(phones):
            return None
    except (TypeError, ValueError):
        pass
    if not phones:
        return None
    try:
        if isinstance(phones, str):
            import json as _j
            phones = _j.loads(phones.replace("'", '"'))
        if not isinstance(phones, list):
            return None
        # Prefer primary mobile, then any primary, then first entry
        for p in phones:
            if isinstance(p, dict) and p.get("primary") and "mobile" in str(p.get("type", "")).lower():
                return str(p["number"])
        for p in phones:
            if isinstance(p, dict) and p.get("primary"):
                return str(p["number"])
        if isinstance(phones[0], dict):
            return str(phones[0].get("number", ""))
    except Exception:
        pass
    return None


def _score_row(row) -> int:
    score = 0
    try:
        yr = int(_safe_str(row.get("year_built")) or 0)
        if yr and yr < 1980:
            score += 40
        elif yr and yr < 1995:
            score += 25
        elif yr and yr < 2005:
            score += 10
    except Exception:
        pass

    try:
        days = int(_safe_str(row.get("days_on_mls")) or 0)
        if days >= 90:
            score += 30
        elif days >= 45:
            score += 20
        elif days >= 20:
            score += 10
    except Exception:
        pass

    style = _safe_str(row.get("style")).lower()
    for kw in ("ranch", "colonial", "victorian", "bungalow", "cape cod", "split level"):
        if kw in style:
            score += 10
            break

    try:
        price_raw = _safe_str(row.get("list_price")) or _safe_str(row.get("sold_price")) or "0"
        price = int(price_raw or 0)
        if 80_000 < price < 400_000:
            score += 10
    except Exception:
        pass

    return score


def _scrape(location, listing_type, past_days, extra_property_data=False, radius=None):
    from homeharvest import scrape_property
    try:
        kwargs = dict(
            location=location,
            listing_type=listing_type,
            past_days=past_days,
            extra_property_data=extra_property_data,
        )
        if radius is not None:
            kwargs["radius"] = float(radius)
        return scrape_property(**kwargs)
    except Exception:
        return None


def fetch_leads(location: str, radius_miles: int = 25, max_leads: int = 10) -> list[dict]:
    """Active Realtor.com listings scored by painting likelihood."""
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []

    df = _scrape(location, "for_sale", 180, radius=radius_miles)
    if df is None or df.empty:
        return []

    df = df[df["new_construction"].isna() | (df["new_construction"] == False)].copy()
    df["_score"] = df.apply(_score_row, axis=1)
    df = df.sort_values("_score", ascending=False).head(max_leads * 2)

    leads = []
    for _, row in df.iterrows():
        address = (_safe_str(row.get("formatted_address")) or
                   _safe_str(row.get("full_street_line")))
        if not address:
            continue
        leads.append({
            "address":    address,
            "year_built": int(row["year_built"]) if pd.notna(row.get("year_built")) else None,
            "days_on_mls":int(row["days_on_mls"]) if pd.notna(row.get("days_on_mls")) else None,
            "list_price": int(row["list_price"])  if pd.notna(row.get("list_price"))  else None,
            "style":      _safe_str(row.get("style")) or None,
            "score":      int(row["_score"]),
            "lead_type":  "for_sale",
            "agent_name": _safe_str(row.get("agent_name")) or None,
            "agent_email":_safe_str(row.get("agent_email")) or None,
            "agent_phone":_extract_phone(row.get("agent_phones")),
            "broker_name":_safe_str(row.get("broker_name")) or None,
        })
        if len(leads) >= max_leads:
            break
    return leads


def fetch_recently_sold(location: str, max_leads: int = 8) -> list[dict]:
    """
    Recently sold homes (past 45 days) — new owners are the hottest painting leads.
    People who just bought almost always repaint before moving in.
    """
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []

    df = _scrape(location, "sold", 45)
    if df is None or df.empty:
        return []

    df = df[df["new_construction"].isna() | (df["new_construction"] == False)].copy()
    df["_score"] = df.apply(_score_row, axis=1)
    df = df.sort_values("_score", ascending=False).head(max_leads * 2)

    leads = []
    for _, row in df.iterrows():
        address = (_safe_str(row.get("formatted_address")) or
                   _safe_str(row.get("full_street_line")))
        if not address:
            continue
        sold_price = int(row["sold_price"]) if pd.notna(row.get("sold_price")) else None
        leads.append({
            "address":    address,
            "year_built": int(row["year_built"]) if pd.notna(row.get("year_built")) else None,
            "sold_price": sold_price,
            "style":      _safe_str(row.get("style")) or None,
            "score":      int(row["_score"]),
            "lead_type":  "recently_sold",
            "agent_name": _safe_str(row.get("agent_name")) or None,
            "agent_email":_safe_str(row.get("agent_email")) or None,
            "agent_phone":_extract_phone(row.get("agent_phones")),
            "broker_name":_safe_str(row.get("broker_name")) or None,
        })
        if len(leads) >= max_leads:
            break
    return leads


def format_leads_for_agent(leads: list[dict]) -> str:
    """Format active listings for agent context."""
    if not leads:
        return ""
    lines = ["=== REALTOR.COM — Active Listings (for sale, likely need painting) ==="]
    for i, lead in enumerate(leads, 1):
        yr    = f", built {lead['year_built']}"      if lead.get("year_built")  else ""
        days  = f", {lead['days_on_mls']} days listed" if lead.get("days_on_mls") is not None else ""
        price = f", ${lead['list_price']:,}"          if lead.get("list_price")  else ""
        style = f" [{lead['style']}]"                 if lead.get("style")       else ""
        lines.append(f"{i}. {lead['address']}{style}{yr}{days}{price}")
    return "\n".join(lines)


def format_recently_sold_for_agent(leads: list[dict]) -> str:
    """Format recently sold homes for agent context."""
    if not leads:
        return ""
    lines = ["=== REALTOR.COM — Recently Sold (past 45 days) — NEW OWNERS = HOT LEADS ==="]
    for i, lead in enumerate(leads, 1):
        yr    = f", built {lead['year_built']}" if lead.get("year_built") else ""
        price = f", sold ${lead['sold_price']:,}" if lead.get("sold_price") else ""
        style = f" [{lead['style']}]"            if lead.get("style")      else ""
        lines.append(f"{i}. {lead['address']}{style}{yr}{price}  [NEW OWNER]")
    return "\n".join(lines)
