"""
Residential owner contact lookup via Google Custom Search API.
Uses free tier (100 queries/day) — no extra cost beyond existing GOOGLE_API_KEY.
Requires a Google Custom Search Engine ID (GOOGLE_CSE_ID) — free setup at:
  https://programmablesearchengine.google.com/

How it works:
  1. Searches Google for "<address> owner" using Custom Search API
  2. Parses result snippets for names, phone numbers, emails
  3. Returns best match with source attribution
"""

import re
import requests

_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

# Phone number pattern — matches (123) 456-7890, 123-456-7890, 1234567890, +1 etc.
_PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?"
    r"(?:\(?\d{3}\)?[-.\s]?)"
    r"\d{3}[-.\s]?\d{4}"
)

# Name pattern — two or three capitalised words (First Last or First M Last)
_NAME_RE = re.compile(
    r"\b([A-Z][a-z]{1,20}(?:\s[A-Z]\.?)?\s[A-Z][a-z]{1,25})\b"
)

# Email pattern
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Noise words that are not person names
_NON_NAME_WORDS = {
    "United States", "New York", "Los Angeles", "San Francisco",
    "Search Results", "Real Estate", "White Pages", "View Profile",
    "Phone Number", "Background Check", "Find Contact",
    "Current Address", "Public Records", "Property Records",
    "Rhode Island", "South Carolina", "North Carolina", "New Jersey",
    "New Mexico", "West Virginia", "New Hampshire",
}


def _clean_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return p.strip()


def _parse_snippets(items: list[dict]) -> dict:
    """Extract best name + phone + email from a list of Google result items."""
    names, phones, emails = [], [], []

    for item in items:
        text = " ".join([
            item.get("title", ""),
            item.get("snippet", ""),
            item.get("htmlSnippet", ""),
        ])

        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", text)

        for m in _PHONE_RE.finditer(text):
            p = _clean_phone(m.group())
            if p and p not in phones:
                phones.append(p)

        for m in _EMAIL_RE.finditer(text):
            e = m.group()
            if e not in emails and "google" not in e.lower():
                emails.append(e)

        for m in _NAME_RE.finditer(text):
            n = m.group()
            if n not in _NON_NAME_WORDS and n not in names:
                names.append(n)

    return {
        "name":  names[0]  if names  else None,
        "phone": phones[0] if phones else None,
        "email": emails[0] if emails else None,
    }


def lookup_owner_contact(
    address: str,
    api_key: str,
    cse_id: str,
) -> dict:
    """
    Search Google for owner contact info for a residential address.
    Returns dict with keys: name, phone, email, source (all may be None).
    """
    if not api_key or not cse_id or not address:
        return {"name": None, "phone": None, "email": None, "source": None}

    # Clean up address — remove property metadata like "[SINGLE_FAMILY], built..."
    clean_addr = re.split(r"\[|\bbuilt\b|\bdays\b", address)[0].strip().rstrip(",")

    query = f'"{clean_addr}" owner contact'

    try:
        r = requests.get(
            _SEARCH_URL,
            params={
                "key": api_key,
                "cx":  cse_id,
                "q":   query,
                "num": 5,
            },
            timeout=8,
        )
        if r.status_code != 200:
            return {"name": None, "phone": None, "email": None, "source": None}

        items = r.json().get("items", [])
        if not items:
            return {"name": None, "phone": None, "email": None, "source": None}

        contact = _parse_snippets(items)
        contact["source"] = "Google Search"
        return contact

    except Exception:
        return {"name": None, "phone": None, "email": None, "source": None}


def enrich_leads_with_contacts(
    leads: list[dict],
    api_key: str,
    cse_id: str,
    max_lookups: int = 10,
) -> list[dict]:
    """
    Enrich a list of residential leads with owner contact info.
    Limits API calls to max_lookups to stay within free tier (100/day).
    """
    if not api_key or not cse_id:
        return leads

    enriched = []
    count = 0
    for lead in leads:
        if count < max_lookups and lead.get("lead_type") in ("for_sale", "recently_sold"):
            contact = lookup_owner_contact(lead["address"], api_key, cse_id)
            lead = {**lead, **{f"owner_{k}": v for k, v in contact.items()}}
            count += 1
        enriched.append(lead)
    return enriched
