# Copyright (c) 2024 Vijay JPS. All Rights Reserved.
# Unauthorized copying, modification, distribution, or use of this software,
# via any medium, is strictly prohibited without the express written permission
# of the owner.
import re
import html as _html
import json as _json
import requests
import streamlit as st
from streamlit_folium import st_folium

try:
    from crew import run_crew
    CREW_AVAILABLE = True
except Exception:
    CREW_AVAILABLE = False

from utils.llm_factory import get_available_models, get_provider_info
from utils.lead_tracker import (
    save_leads, update_lead, get_all_leads, get_pipeline_summary,
    delete_lead, STATUSES
)
from utils.material_estimator import estimate as material_estimate, days_to_peak_season
from utils.pdf_generator import generate_proposal_pdf
from utils.map_utils import build_leads_map
from dotenv import load_dotenv, set_key
import os
import logging
import base64
from datetime import datetime, timezone
from pathlib import Path

load_dotenv()

# On Streamlit Community Cloud there is no .env file — bridge st.secrets → os.environ
# so every os.getenv() call in crew.py / llm_factory.py / tools still works.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

STATE_CITY_MAP = {
    "Alabama": "Montgomery", "Alaska": "Juneau", "Arizona": "Phoenix",
    "Arkansas": "Little Rock", "California": "Sacramento", "Colorado": "Denver",
    "Connecticut": "Hartford", "Delaware": "Dover", "Florida": "Tallahassee",
    "Georgia": "Atlanta", "Hawaii": "Honolulu", "Idaho": "Boise",
    "Illinois": "Springfield", "Indiana": "Indianapolis", "Iowa": "Des Moines",
    "Kansas": "Topeka", "Kentucky": "Frankfort", "Louisiana": "Baton Rouge",
    "Maine": "Augusta", "Maryland": "Annapolis", "Massachusetts": "Boston",
    "Michigan": "Lansing", "Minnesota": "St. Paul", "Mississippi": "Jackson",
    "Missouri": "Jefferson City", "Montana": "Helena", "Nebraska": "Lincoln",
    "Nevada": "Carson City", "New Hampshire": "Concord", "New Jersey": "Trenton",
    "New Mexico": "Santa Fe", "New York": "Albany", "North Carolina": "Raleigh",
    "North Dakota": "Bismarck", "Ohio": "Columbus", "Oklahoma": "Oklahoma City",
    "Oregon": "Salem", "Pennsylvania": "Harrisburg", "Rhode Island": "Providence",
    "South Carolina": "Columbia", "South Dakota": "Pierre", "Tennessee": "Nashville",
    "Texas": "Austin", "Utah": "Salt Lake City", "Vermont": "Montpelier",
    "Virginia": "Richmond", "Washington": "Olympia", "West Virginia": "Charleston",
    "Wisconsin": "Madison", "Wyoming": "Cheyenne",
}
STATE_NAMES = list(STATE_CITY_MAP.keys())


def parse_location(location: str) -> "tuple[str, str]":
    location = (location or "").strip()
    if "," in location:
        parts = [p.strip() for p in location.split(",") if p.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]
    m = re.match(r"^(.*?)[, ]+([A-Za-z]{2})$", location)
    if m:
        return m.group(1).strip(), m.group(2).strip().upper()
    return location, ""


def detect_user_location() -> str | None:
    """Detect city/state from the user's public IP. Returns 'City, ST' or None."""
    try:
        r = requests.get("https://ipapi.co/json/", timeout=4)
        if r.status_code == 200:
            d = r.json()
            city  = (d.get("city") or "").strip()
            abbr  = (d.get("region_code") or "").strip()
            if city and abbr:
                return f"{city}, {abbr}"
    except Exception:
        pass
    return None


def get_env_path() -> Path:
    p = Path(__file__).resolve().parent / ".env"
    if not p.exists():
        p.write_text("")
    return p


def save_env_value(key: str, value: str):
    set_key(str(get_env_path()), key, value)
    os.environ[key] = value


def extract_scope_items(analyzer_text: str) -> list[str]:
    """Parse prep/scope work items from AI analyzer output. Falls back to sensible defaults."""
    prep_kw = [
        "power wash", "pressure wash", "scrape", "scraping", "prime", "primer",
        "sand", "sanding", "caulk", "caulking", "repair", "patch", "patching",
        "clean", "strip", "fill", "rot", "rust", "bare wood", "peeling",
        "wash", "preparation", "prep",
    ]
    found = []
    for line in analyzer_text.splitlines():
        ll = line.lower()
        if any(kw in ll for kw in prep_kw):
            clean = line.lstrip("- *•\t#>").strip()
            if 8 < len(clean) < 140:
                found.append(clean)

    # deduplicate (keep first occurrence)
    seen, unique = set(), []
    for item in found:
        key = item.lower()[:35]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # always append standard finishing steps if not already detected
    always = [
        "Two coats exterior paint",
        "Trim & accent painting",
        "Clean-up & final walkthrough with client",
    ]
    for step in always:
        if not any(step.lower()[:20] in u.lower() for u in unique):
            unique.append(step)

    return unique[:10] if unique else [
        "Surface preparation & power washing",
        "Scraping & sanding loose paint",
        "Primer coat on bare surfaces",
        "Two coats exterior paint",
        "Trim & accent painting",
        "Clean-up & final walkthrough with client",
    ]


def send_email(draft: str, recipient_email: str, image_path: str = None, subject: str = "Free Color Consultation for Your Home") -> bool:
    api_key    = os.getenv("BREVO_API_KEY")
    from_email = os.getenv("FROM_EMAIL")
    from_name  = os.getenv("FROM_NAME")
    missing = [n for n, v in [("BREVO_API_KEY", api_key), ("FROM_EMAIL", from_email), ("FROM_NAME", from_name)] if not v]
    if missing:
        st.error(f"Cannot send email: missing {', '.join(missing)}")
        return False
    headers = {"accept": "application/json", "api-key": api_key, "content-type": "application/json"}
    safe_body = _html.escape(draft).replace("\n", "<br>")
    data = {
        "sender":      {"name": from_name, "email": from_email},
        "to":          [{"email": recipient_email}],
        "subject":     subject,
        "htmlContent": f"<p>{safe_body}</p>",
    }
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            data["attachment"] = [{"name": "visualization.png", "content": base64.b64encode(f.read()).decode()}]
    r = requests.post("https://api.brevo.com/v3/smtp/email", headers=headers, json=data)
    if r.status_code != 201:
        st.error(f"Email failed: {r.text}")
        return False
    return True


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PaintPro AI | Lead Generation",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Full CSS Theme ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@700;800;900&family=Inter:wght@400;500;600;700&display=swap');

/* ─── Base ──────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}
.stApp {
    background: #F2EDE6 !important;
}
.main .block-container {
    padding: 1.5rem 2.5rem 4rem !important;
    max-width: 1280px !important;
}

/* Default text colour — overridden by component-specific rules with !important */
p, span, div, label, li {
    color: #1C2B3A;
}
/* Prevent the global rule from bleeding into tab buttons */
.stTabs [data-baseweb="tab"] * { color: inherit; }
.stTabs [aria-selected="true"] * { color: #FFFFFF !important; }
h1, h2, h3, h4, h5, h6 {
    font-family: 'Montserrat', sans-serif !important;
    color: #1C2B3A !important;
    font-weight: 800 !important;
}

/* ─── Sidebar ───────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: #1C2B3A !important;
}
section[data-testid="stSidebar"] * {
    color: #C8D8E8 !important;
    font-family: 'Inter', sans-serif !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] strong {
    color: #F5A623 !important;
    font-family: 'Montserrat', sans-serif !important;
}
section[data-testid="stSidebar"] .stCaption,
section[data-testid="stSidebar"] .stCaption * {
    color: #8AAFCC !important;
    font-size: 0.78rem !important;
}
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea {
    background: #243448 !important;
    border: 1px solid #364F6A !important;
    color: #E8F2FF !important;
    border-radius: 8px !important;
    font-size: 0.88rem !important;
}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div {
    background: #243448 !important;
    border: 1px solid #364F6A !important;
    color: #E8F2FF !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] svg {
    fill: #C8D8E8 !important;
}
section[data-testid="stSidebar"] hr {
    border-color: #2C4060 !important;
    margin: 0.8rem 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] {
    background: #243448 !important;
    border: 1px solid #364F6A !important;
    border-radius: 10px !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #C8D8E8 !important;
}

/* ─── Primary button ────────────────────────────────────────────── */
button[kind="primary"] {
    background: linear-gradient(135deg, #D4520A 0%, #F5A623 100%) !important;
    border: none !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 1rem !important;
    border-radius: 50px !important;
    padding: 0.6rem 2.4rem !important;
    letter-spacing: 0.3px !important;
    box-shadow: 0 4px 20px rgba(212, 82, 10, 0.40) !important;
    transition: all 0.2s ease !important;
}
button[kind="primary"]:hover {
    box-shadow: 0 8px 28px rgba(212, 82, 10, 0.55) !important;
    transform: translateY(-2px) !important;
}

/* ─── Download buttons ──────────────────────────────────────────── */
.stDownloadButton > button {
    background: #FFFFFF !important;
    border: 2px solid #1C2B3A !important;
    color: #1C2B3A !important;
    font-weight: 700 !important;
    font-size: 0.9rem !important;
    border-radius: 50px !important;
    padding: 0.5rem 1.8rem !important;
    transition: all 0.2s ease !important;
}
.stDownloadButton > button:hover {
    background: #1C2B3A !important;
    color: #FFFFFF !important;
}

/* ─── Tabs ──────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: #FFFFFF !important;
    border-radius: 16px !important;
    padding: 6px 7px !important;
    gap: 4px !important;
    box-shadow: 0 2px 16px rgba(0,0,0,0.09) !important;
    border: 1px solid #E0D8CF !important;
    margin-bottom: 1.6rem !important;
}
/* unselected tab — button + all inner text nodes */
.stTabs [data-baseweb="tab"] {
    border-radius: 12px !important;
    color: #3A5068 !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.87rem !important;
    padding: 0.55rem 1.2rem !important;
    border: none !important;
    background: transparent !important;
    transition: background 0.15s ease, color 0.15s ease !important;
}
.stTabs [data-baseweb="tab"] p,
.stTabs [data-baseweb="tab"] span,
.stTabs [data-baseweb="tab"] div {
    color: #3A5068 !important;
    font-weight: 600 !important;
}
/* hover on unselected */
.stTabs [data-baseweb="tab"]:hover {
    background: #F5EEE6 !important;
    color: #1C2B3A !important;
}
.stTabs [data-baseweb="tab"]:hover p,
.stTabs [data-baseweb="tab"]:hover span,
.stTabs [data-baseweb="tab"]:hover div {
    color: #1C2B3A !important;
}
/* selected tab — orange-amber gradient, always white text */
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #D4520A 0%, #F5A623 100%) !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    box-shadow: 0 3px 14px rgba(212,82,10,0.38) !important;
}
.stTabs [aria-selected="true"] p,
.stTabs [aria-selected="true"] span,
.stTabs [aria-selected="true"] div {
    color: #FFFFFF !important;
    font-weight: 700 !important;
}
/* tab panel content area */
.stTabs [data-baseweb="tab-panel"] {
    padding: 0 !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {
    display: none !important;
}

/* ─── Metric cards ──────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border-radius: 14px !important;
    padding: 1.2rem !important;
    border: 1px solid #E0D8CF !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06) !important;
}
[data-testid="stMetricLabel"] > div {
    color: #5A7080 !important;
    font-size: 0.74rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.7px !important;
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stMetricValue"] > div {
    color: #1C2B3A !important;
    font-family: 'Montserrat', sans-serif !important;
    font-weight: 800 !important;
    font-size: 1.9rem !important;
}

/* ─── White cards / containers ──────────────────────────────────── */
[data-testid="stContainer"] {
    background: #FFFFFF !important;
    border-radius: 14px !important;
    border: 1px solid #E0D8CF !important;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05) !important;
}
[data-testid="stExpander"] {
    background: #FFFFFF !important;
    border: 1px solid #E0D8CF !important;
    border-radius: 12px !important;
}
[data-testid="stExpander"] summary {
    color: #1C2B3A !important;
    font-weight: 600 !important;
}

/* ─── Text inputs ───────────────────────────────────────────────── */
.stTextInput input, .stTextArea textarea, .stNumberInput input {
    background: #FFFFFF !important;
    border: 2px solid #D0C8BE !important;
    border-radius: 10px !important;
    color: #1C2B3A !important;
    font-size: 0.92rem !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #D4520A !important;
    box-shadow: 0 0 0 3px rgba(212,82,10,0.14) !important;
}
.stTextInput label, .stTextArea label, .stNumberInput label,
.stSelectbox label, .stSlider label, .stCheckbox label {
    color: #1C2B3A !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
}

/* ─── Selectbox ─────────────────────────────────────────────────── */
.stSelectbox > div > div {
    background: #FFFFFF !important;
    border: 2px solid #D0C8BE !important;
    border-radius: 10px !important;
    color: #1C2B3A !important;
}

/* ─── Alerts ────────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 12px !important;
    font-weight: 500 !important;
}

/* ─── File uploader ─────────────────────────────────────────────── */
[data-testid="stFileUploader"] {
    background: #FFFFFF !important;
    border: 2px dashed #C8B8A8 !important;
    border-radius: 14px !important;
}

/* ─── Checkbox ──────────────────────────────────────────────────── */
.stCheckbox label {
    color: #1C2B3A !important;
    font-size: 0.9rem !important;
}

/* ─── Scrollbar ─────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #EDE6DC; }
::-webkit-scrollbar-thumb { background: #B8A898; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #9A8878; }

hr { border-color: #E0D8CF !important; }

/* ─── Radio ─────────────────────────────────────────────────────── */
.stRadio label { color: #1C2B3A !important; font-weight: 500 !important; font-size: 0.9rem !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────
for key, default in [
    ("history",    []),
    ("last_leads", []),
    ("last_result", None),
    ("location_auto_detected", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

if "target_location" not in st.session_state:
    _env_loc   = os.getenv("TARGET_LOCATION", "") or ""
    _detected  = detect_user_location() if not _env_loc else None
    st.session_state.target_location       = _detected or _env_loc or "Springfield, IL"
    st.session_state.location_auto_detected = bool(_detected)

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.markdown("""
<div style="text-align:center; padding:1.4rem 0 0.8rem;">
  <div style="font-size:3.2rem; line-height:1;">&#127912;</div>
  <div style="color:#F5A623; font-family:'Montserrat',sans-serif; font-weight:900;
              font-size:1.35rem; letter-spacing:-0.3px; margin-top:8px;">PaintPro AI</div>
  <div style="color:#3D5A78; font-size:0.65rem; letter-spacing:2.5px;
              text-transform:uppercase; margin-top:4px;">Lead Generation Suite</div>
</div>
<hr>
""", unsafe_allow_html=True)

st.sidebar.markdown("""
<p style="color:#F5A623 !important; font-family:'Montserrat',sans-serif !important;
          font-weight:700 !important; font-size:0.75rem !important;
          text-transform:uppercase; letter-spacing:1.5px; margin-bottom:6px;">
  Target Location
</p>""", unsafe_allow_html=True)

all_locations = sorted([f"{city}, {state}" for state, city in STATE_CITY_MAP.items()])
_current_loc = st.session_state.target_location
if _current_loc not in all_locations:
    all_locations.insert(0, _current_loc)

if st.session_state.location_auto_detected:
    st.sidebar.markdown(
        f'<div style="background:rgba(39,174,96,0.15);border:1px solid rgba(39,174,96,0.35);'
        f'border-radius:8px;padding:7px 12px;margin-bottom:8px;display:flex;align-items:center;gap:8px;">'
        f'<span style="font-size:0.9rem;">&#128205;</span>'
        f'<span style="color:#2ECC71;font-size:0.78rem;font-weight:600;">Auto-detected: {_current_loc}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

selected_location = st.sidebar.selectbox(
    "Target Location", options=all_locations,
    index=all_locations.index(_current_loc) if _current_loc in all_locations else 0,
    label_visibility="collapsed",
)
custom_location = st.sidebar.text_input("Custom location", value="", placeholder="e.g. Boston, MA or 10001")
if custom_location.strip():
    st.session_state.target_location        = custom_location.strip()
    st.session_state.location_auto_detected = False
elif selected_location != _current_loc:
    st.session_state.target_location        = selected_location
    st.session_state.location_auto_detected = False

city, state = parse_location(st.session_state.target_location)
ca, cb = st.sidebar.columns(2)
ca.text_input("City",  value=city,  disabled=True)
cb.text_input("State", value=state, disabled=True)
search_radius = st.sidebar.slider("Search Radius (miles)", 1, 200, 10, 5)

st.sidebar.markdown("""<hr>
<p style="color:#F5A623 !important; font-family:'Montserrat',sans-serif !important;
          font-weight:700 !important; font-size:0.75rem !important;
          text-transform:uppercase; letter-spacing:1.5px; margin-bottom:6px;">
  AI Model
</p>""", unsafe_allow_html=True)

provider_info    = get_provider_info()
provider_options = list(provider_info.keys())
default_provider = os.getenv("LLM_PROVIDER", "groq")
if default_provider not in provider_options:
    default_provider = "groq"
selected_provider = st.sidebar.selectbox(
    "LLM Provider", options=provider_options,
    index=provider_options.index(default_provider), label_visibility="collapsed",
)
provider = provider_info[selected_provider]
st.sidebar.caption(f"**{provider['name']}** — {provider['cost']} · {provider['speed']}")
st.sidebar.caption(provider["note"])
available_models = get_available_models(selected_provider)
selected_model   = st.sidebar.selectbox("Model", options=available_models, index=0, label_visibility="collapsed")
mock_mode        = st.sidebar.checkbox("Use Mock Mode", value=not CREW_AVAILABLE)

PROVIDER_KEY_ENV = {
    "groq": "GROQ_API_KEY", "gemini": "GOOGLE_API_KEY", "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY", "cerebras": "CEREBRAS_API_KEY", "ollama": "OLLAMA_BASE_URL",
}
required_key         = PROVIDER_KEY_ENV.get(selected_provider)
provider_key_present = bool(os.getenv(required_key)) if required_key else False

if mock_mode:
    st.sidebar.info("Mock Mode enabled.")
elif not provider_key_present:
    st.sidebar.error(f"{selected_provider} requires {required_key}.")
else:
    st.sidebar.markdown("""
    <div style="background:rgba(39,174,96,0.15); border:1px solid rgba(39,174,96,0.4);
                border-radius:9px; padding:9px 14px; margin-top:6px;">
      <span style="color:#2ECC71 !important; font-weight:700; font-size:0.82rem;">
        &#10003; Live AI mode active
      </span>
    </div>""", unsafe_allow_html=True)

st.sidebar.markdown("<hr>", unsafe_allow_html=True)
with st.sidebar.expander("🔑  API Keys", expanded=False):
    groq_key_input      = st.text_input("Groq API Key",      value=os.getenv("GROQ_API_KEY",""),     type="password", help="Free: console.groq.com")
    cerebras_key_input  = st.text_input("Cerebras API Key",  value=os.getenv("CEREBRAS_API_KEY",""), type="password", help="Free: cloud.cerebras.ai")
    google_key_input    = st.text_input("Google API Key",    value=os.getenv("GOOGLE_API_KEY",""),   type="password", help="Free: aistudio.google.com — also used for Places & Custom Search")
    google_cse_input    = st.text_input("Google CSE ID",     value=os.getenv("GOOGLE_CSE_ID",""),    help="Custom Search Engine ID — free setup at programmablesearchengine.google.com (enables owner contact lookup)")
    anthropic_key_input = st.text_input("Anthropic Key",     value=os.getenv("ANTHROPIC_API_KEY",""),type="password")
    openai_key_input    = st.text_input("OpenAI Key",        value=os.getenv("OPENAI_API_KEY",""),   type="password")
    ollama_url_input    = st.text_input("Ollama Base URL",   value=os.getenv("OLLAMA_BASE_URL","http://localhost:11434"))
    if st.button("Save Keys", type="primary"):
        for k, v in [
            ("GROQ_API_KEY", groq_key_input), ("CEREBRAS_API_KEY", cerebras_key_input),
            ("GOOGLE_API_KEY", google_key_input), ("GOOGLE_CSE_ID", google_cse_input),
            ("ANTHROPIC_API_KEY", anthropic_key_input),
            ("OPENAI_API_KEY", openai_key_input), ("OLLAMA_BASE_URL", ollama_url_input),
        ]:
            if v:
                save_env_value(k, v)
        st.sidebar.success("Keys saved — refresh to apply.")

with st.sidebar.expander("🏢  Company Settings", expanded=False):
    company_name = st.text_input("Company Name", value="Your Painting Company")

st.sidebar.markdown(f"""
<div style="margin-top:1.4rem; padding:14px 16px; background:rgba(255,255,255,0.06);
            border-radius:12px; border:1px solid #2C4060;">
  <div style="color:#3D5A78; font-size:0.65rem; text-transform:uppercase;
              letter-spacing:1.2px; margin-bottom:7px;">Active Session</div>
  <div style="color:#DDEEFF; font-size:0.88rem; font-weight:600;">
    &#128205; {st.session_state.target_location}</div>
  <div style="color:#3D5A78; font-size:0.76rem; margin-top:4px;">
    {search_radius} mi radius &middot; {provider['name']}
  </div>
</div>
""", unsafe_allow_html=True)

# ── Hero Banner ────────────────────────────────────────────────────────────────
days_away, season_label = days_to_peak_season()

if days_away == 0:
    season_html = (
        f'<div style="background:linear-gradient(135deg,#1A5C38,#27AE60);color:#FFFFFF;'
        f'padding:14px 24px;border-radius:14px;margin-bottom:0;display:flex;'
        f'align-items:center;gap:14px;box-shadow:0 4px 16px rgba(39,174,96,0.30);">'
        f'<span style="font-size:1.8rem;">&#9728;&#65039;</span>'
        f'<div><span style="font-weight:700;font-size:1rem;">{season_label}</span>'
        f'<span style="font-size:0.88rem;opacity:0.9;"> &mdash; Prime time for exterior painting jobs!</span>'
        f'</div></div>'
    )
else:
    season_html = (
        f'<div style="background:linear-gradient(135deg,#1A3E72,#2D7DD2);color:#FFFFFF;'
        f'padding:14px 24px;border-radius:14px;margin-bottom:0;display:flex;'
        f'align-items:center;gap:14px;box-shadow:0 4px 16px rgba(45,125,210,0.25);">'
        f'<span style="font-size:1.8rem;">&#128197;</span>'
        f'<div><span style="font-weight:700;font-size:1rem;">{season_label}</span>'
        f'<span style="font-size:0.88rem;opacity:0.9;"> &mdash; Start building your pipeline now.</span>'
        f'</div></div>'
    )

_total_leads = len(get_all_leads())
_leads_label = f"{_total_leads}" if _total_leads > 0 else "—"
stat_items = [(_leads_label, "Total CRM Leads"), ("$0", "Platform Cost"), (str(len(provider_options)), "AI Providers"), ("Free", "Hosting")]
stat_html = "".join(
    f'<div style="text-align:center;background:rgba(255,255,255,0.10);border-radius:14px;'
    f'padding:12px 18px;border:1px solid rgba(255,255,255,0.15);min-width:80px;">'
    f'<div style="color:#F5A623;font-size:1.5rem;font-weight:900;'
    f'font-family:\'Montserrat\',sans-serif;line-height:1;white-space:nowrap;">{v}</div>'
    f'<div style="color:#8AAFCC;font-size:0.65rem;text-transform:uppercase;'
    f'letter-spacing:1px;margin-top:4px;font-weight:600;white-space:nowrap;">{l}</div>'
    f'</div>'
    for v, l in stat_items
)

st.markdown(f"""
<div style="background:linear-gradient(140deg,#1C2B3A 0%,#1E3A5F 55%,#2C4F82 100%);
            border-radius:24px; padding:2.8rem 3.2rem; margin-bottom:1.4rem;
            position:relative; overflow:hidden;
            box-shadow:0 12px 48px rgba(28,43,58,0.32);">
  <!-- decorative blobs -->
  <div style="position:absolute; top:-60px; right:-60px; width:280px; height:280px;
              background:rgba(245,166,35,0.07); border-radius:50%; pointer-events:none;"></div>
  <div style="position:absolute; bottom:-80px; right:80px; width:220px; height:220px;
              background:rgba(212,82,10,0.06); border-radius:50%; pointer-events:none;"></div>
  <!-- big emoji watermarks -->
  <div style="position:absolute; top:12px; right:60px; font-size:7rem;
              opacity:0.08; transform:rotate(-12deg); pointer-events:none;">&#127912;</div>
  <div style="position:absolute; bottom:6px; right:18px; font-size:4.5rem;
              opacity:0.06; transform:rotate(8deg); pointer-events:none;">&#128396;&#65039;</div>

  <div style="position:relative; z-index:1;">
    <!-- badge -->
    <div style="display:inline-flex; align-items:center; gap:8px;
                background:linear-gradient(135deg,#D4520A,#F5A623); color:#FFFFFF;
                padding:6px 20px; border-radius:50px; font-size:0.7rem;
                font-weight:700; letter-spacing:2px; margin-bottom:18px;">
      &#9889; AI-POWERED LEAD GENERATION
    </div>
    <!-- title -->
    <div style="color:#FFFFFF; font-size:3.2rem; font-weight:900; line-height:1.05;
                font-family:'Montserrat',sans-serif; margin-bottom:10px;
                text-shadow:0 3px 24px rgba(0,0,0,0.30);">
      Paint<span style="color:#F5A623;">Pro</span> AI
    </div>
    <!-- subtitle -->
    <p style="color:#90B8D8; font-size:1.05rem; margin:0 0 2rem;
              max-width:520px; line-height:1.75; font-weight:400;">
      Find homeowners ready for exterior painting. AI prospecting, instant
      quotes, outreach emails, CRM pipeline &amp; photo assessment &mdash; 100&percnt; free.
    </p>
    <!-- stats row -->
    <div style="display:flex; gap:14px; flex-wrap:wrap;">{stat_html}</div>
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown(season_html, unsafe_allow_html=True)

if not CREW_AVAILABLE:
    st.error("CrewAI not installed. Run: pip install crewai")

# ══════════════════════════════════════════════════════════════════════════════
# Tabs
# ══════════════════════════════════════════════════════════════════════════════
main_tabs = st.tabs([
    "🔍  Lead Generation",
    "🗺️  Lead Map",
    "📋  CRM Pipeline",
    "🧮  Material Estimator",
    "📸  Photo Assessment",
])

# ─── Shared card helpers ───────────────────────────────────────────────────────
def card(body: str, padding="1.4rem 1.8rem", bg="#FFFFFF", border="#E0D8CF", radius="14px", shadow=True):
    sh = "box-shadow:0 2px 12px rgba(0,0,0,0.06);" if shadow else ""
    return f"""<div style="background:{bg};border:1px solid {border};border-radius:{radius};
               padding:{padding};{sh}margin-bottom:10px;">{body}</div>"""


def badge(text: str, bg: str, color: str = "#FFFFFF"):
    return (f"<span style='background:{bg};color:{color};padding:5px 14px;border-radius:50px;"
            f"font-size:0.72rem;font-weight:700;letter-spacing:0.6px;white-space:nowrap;'>{text}</span>")


PRIO_COLORS = {"HOT": "#D4380D", "WARM": "#D4870A", "COLD": "#2563EB"}

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Lead Generation
# ─────────────────────────────────────────────────────────────────────────────
with main_tabs[0]:
    # Tab header
    st.markdown(f"""
    <div style="display:flex; align-items:center; justify-content:space-between;
                flex-wrap:wrap; gap:12px; margin-bottom:1.6rem;">
      <div>
        <h2 style="margin:0; font-size:1.7rem; font-weight:900;">Find Painting Leads</h2>
        <p style="margin:5px 0 0; color:#5A7080; font-size:0.9rem; font-weight:500;">
          &#128205; {st.session_state.target_location} &nbsp;&middot;&nbsp; {search_radius}-mile radius
        </p>
      </div>
      <div style="background:#FFF8EC; border:1px solid #F5D080; border-radius:14px;
                  padding:12px 24px; text-align:center;">
        <div style="color:#A06010; font-weight:700; font-size:0.7rem;
                    text-transform:uppercase; letter-spacing:1px;">Prospecting</div>
        <div style="color:#1C2B3A; font-weight:900; font-size:1.2rem;
                    font-family:'Montserrat',sans-serif;">
          {st.session_state.target_location.split(",")[0]}
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    start_disabled = not mock_mode and not provider_key_present
    if start_disabled:
        st.error(f"Set {required_key} in the API Keys panel, or enable Mock Mode.")

    if st.button("🚀  Start Agent Workflow", disabled=start_disabled, type="primary"):
        with st.spinner("AI agents are prospecting… this takes 1–2 minutes."):
            try:
                if mock_mode:
                    _loc  = st.session_state.target_location
                    _city = _loc.split(",")[0].strip()
                    result = {
                        "prospector": (
                            f"Painting leads in {_loc}:\n\n"
                            f"1. 312 Elm Street, {_city} [COLONIAL], built 1979, 68 days listed — Priority: HOT\n"
                            f"2. 87 Oakwood Drive, {_city} [RANCH], built 1986, 28 days listed — Priority: WARM\n"
                            f"3. 1045 Maple Avenue, {_city} [CRAFTSMAN], built 1962, 91 days listed — Priority: HOT\n"
                            f"4. 560 Birchwood Ln, {_city} [TWO-STORY], built 1994, 14 days listed — Priority: WARM\n"
                            f"5. 203 Cedar Court, {_city}, recently sold [NEW OWNER] — Priority: HOT"
                        ),
                        "analyzer": (
                            f"**Property Analysis — Top 3 Leads in {_loc}**\n\n"
                            f"**Lead 1: 312 Elm Street, {_city}**\n"
                            "- Condition: Fair — 1979 Colonial, visibly faded and chalking exterior\n"
                            "- Prep needed: Power washing, scraping loose paint, caulking window frames, priming bare wood\n"
                            "- Color suggestions: Classic navy blue (#2C3E6B) body, crisp white (#FFFFFF) trim\n"
                            "- Scope: ~2,400 sqft exterior + trim\n"
                            "- Estimated Cost: $4,800–$6,200\n\n"
                            f"**Lead 2: 87 Oakwood Drive, {_city}**\n"
                            "- Condition: Good — 1986 Ranch, south-facing wall fading, minor peeling at eaves\n"
                            "- Prep needed: Pressure washing, light sanding, spot priming\n"
                            "- Color suggestions: Warm sage (#8A9E7A) body, white trim and shutters\n"
                            "- Scope: ~1,800 sqft, partial repaint focus south elevation\n"
                            "- Estimated Cost: $3,100–$4,200\n\n"
                            f"**Lead 3: 1045 Maple Avenue, {_city}**\n"
                            "- Condition: Poor — 1962 Craftsman, extensive peeling, exposed wood rot on fascia\n"
                            "- Prep needed: Full scraping, rot repair & wood replacement, full priming, caulking all joints\n"
                            "- Color suggestions: Charcoal gray (#4A4A4A) body, cream (#F5F0E0) trim, forest green (#3A5A30) accents\n"
                            "- Scope: ~2,100 sqft + deck railings + fascia replacement\n"
                            "- Estimated Cost: $6,500–$9,000"
                        ),
                        "quote_visual": {
                            "quote_range": (
                                f"$3,100 – $9,000 range across 3 properties in {_city}\n\n"
                                "Lead 1 (312 Elm St): $4,800–$6,200 — full repaint, moderate prep\n"
                                "Lead 2 (87 Oakwood Dr): $3,100–$4,200 — partial repaint, light prep\n"
                                "Lead 3 (1045 Maple Ave): $6,500–$9,000 — full repaint, heavy prep + repairs"
                            ),
                            "visual_description": (
                                "Before: chalking, faded exteriors with peeling trim and weathered wood. "
                                "After: fresh curb appeal with bold colour choices that increase property "
                                "value by an estimated 5–10% and attract buyer attention immediately."
                            ),
                            "image_path": "",
                        },
                        "outreach": (
                            f"Subject: Free Colour Consultation for Your Home in {_city}\n\n"
                            f"Dear Homeowner,\n\n"
                            f"I was in your neighbourhood recently and noticed your home at 312 Elm Street "
                            f"in {_city}. The exterior is showing some natural weathering — nothing a "
                            f"professional paint job wouldn't completely transform.\n\n"
                            f"We specialise in exterior repaints across {_city} and would love to offer "
                            f"you a FREE no-obligation colour consultation and on-site quote.\n\n"
                            "What we offer:\n"
                            "  - Free colour chip samples brought to your door\n"
                            "  - Honest written quote within 24 hours\n"
                            "  - 5-year workmanship warranty\n"
                            "  - Fully insured crew\n\n"
                            "Call or text us at [phone], or simply reply to this email.\n\n"
                            f"Looking forward to helping you love your home again.\n\n"
                            f"Best regards,\n{company_name}\n[phone] | [email]"
                        ),
                    }
                else:
                    result = run_crew(st.session_state.target_location, search_radius, selected_model, selected_provider)

                st.session_state.last_result = result
                st.session_state.history.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "location": st.session_state.target_location,
                    "radius": search_radius, "model": selected_model,
                    "provider": selected_provider, "results": result,
                })

                prospector_raw = result.get("prospector", "")
                analyzer_raw   = result.get("analyzer", "")
                quote_visual   = result.get("quote_visual", {})
                outreach_raw   = result.get("outreach", "")

                _no_data = prospector_raw.startswith("NO_REAL_DATA:")
                _daily   = any(k in prospector_raw for k in ("GROQ_DAILY_LIMIT", "tokens per day", "TPD"))
                _rate    = any(k in prospector_raw for k in ("RateLimitError", "tokens per minute")) and not _daily
                _failed  = prospector_raw.startswith(("Crew run failed:", "Fallback:")) or _daily or _rate or "LiteLLM" in prospector_raw

                if _no_data:
                    _msg = prospector_raw.replace("NO_REAL_DATA:", "").strip()
                    st.markdown(f"""
                    <div style="background:linear-gradient(135deg,#2C1810,#4A2010);
                                border:1px solid #C0400A; border-radius:14px;
                                padding:20px 24px; margin:1rem 0;">
                      <div style="display:flex; align-items:center; gap:12px; margin-bottom:10px;">
                        <span style="font-size:1.6rem;">&#128683;</span>
                        <span style="color:#FF8C5A; font-weight:800; font-size:1rem;
                                     font-family:'Montserrat',sans-serif;">
                          No Verified Property Data Found
                        </span>
                      </div>
                      <div style="color:#F0C8A0; font-size:0.88rem; line-height:1.6;">
                        {_html.escape(_msg)}
                      </div>
                      <div style="color:#C87040; font-size:0.8rem; margin-top:10px; font-weight:600;">
                        This tool only shows real, verified addresses — it will never invent leads.
                      </div>
                    </div>""", unsafe_allow_html=True)
                elif _daily:
                    st.error("**Groq Daily Limit Reached.** Add a Cerebras key in API Keys and retry, or wait until midnight UTC.")
                elif _rate:
                    st.warning("**Groq per-minute limit hit.** Wait 1 minute and try again.")
                elif _failed:
                    st.warning(f"Agent error: {prospector_raw[:300]}")

                def _parse_lead_lines(raw: str) -> list[str]:
                    """Group numbered lead lines with their Owner:/Contact: sub-lines."""
                    leads, current = [], None
                    for ln in raw.splitlines():
                        s = ln.strip()
                        if not s:
                            continue
                        if re.match(r'^(\*{1,2})?(\d+[.)]\s|[-•]\s)', s):
                            if current is not None:
                                leads.append(current)
                            current = s
                        elif current is not None and (
                            s.startswith("Owner:") or s.startswith("Contact:")
                        ):
                            current += "\n" + s
                    if current is not None:
                        leads.append(current)
                    return leads

                lead_lines = [] if (_failed or _no_data) else _parse_lead_lines(prospector_raw)
                st.session_state.last_leads = lead_lines

                if lead_lines:
                    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                    save_leads(lead_lines, st.session_state.target_location, run_id)

                quote_range = (
                    quote_visual.get("quote_range", "N/A") if isinstance(quote_visual, dict)
                    else str(quote_visual)[:60]
                )
                subject_line = next(
                    (ln.split(":", 1)[1].strip() for ln in outreach_raw.splitlines()
                     if ln.lower().startswith("subject:")),
                    "Free Color Consultation",
                )

                # ── Success banner ──────────────────────────────────────
                st.markdown("""
                <div style="background:linear-gradient(135deg,#1A5C38,#27AE60); color:#FFFFFF;
                            padding:14px 24px; border-radius:12px; margin:1rem 0;
                            display:flex; align-items:center; gap:14px;
                            box-shadow:0 3px 14px rgba(39,174,96,0.28);">
                  <span style="font-size:1.4rem;">&#10003;</span>
                  <strong style="color:#FFFFFF; font-size:1rem;">
                    Workflow completed successfully!
                  </strong>
                </div>""", unsafe_allow_html=True)

                # ── Metric grid ─────────────────────────────────────────
                hot_count = sum(1 for l in lead_lines if "HOT" in l)
                _qr_lines = quote_range.splitlines() if quote_range and quote_range.strip() and quote_range != "N/A" else []
                q_display = _qr_lines[0] if _qr_lines else "N/A"
                st.markdown(f"""
                <div style="display:grid; grid-template-columns:repeat(4,1fr);
                            gap:16px; margin:1rem 0 1.8rem;">
                  <div style="background:#FFFFFF; border-radius:16px; padding:1.4rem;
                              text-align:center; border:1px solid #E0D8CF;
                              box-shadow:0 2px 14px rgba(0,0,0,0.07);">
                    <div style="font-size:2rem; margin-bottom:4px;">&#127968;</div>
                    <div style="color:#1C2B3A; font-size:2.2rem; font-weight:900;
                                font-family:'Montserrat',sans-serif;">{len(lead_lines)}</div>
                    <div style="color:#5A7080; font-size:0.72rem; text-transform:uppercase;
                                letter-spacing:0.7px; font-weight:700; margin-top:2px;">Leads Found</div>
                  </div>
                  <div style="background:#FFFFFF; border-radius:16px; padding:1.4rem;
                              text-align:center; border:1px solid #E0D8CF;
                              box-shadow:0 2px 14px rgba(0,0,0,0.07);">
                    <div style="font-size:2rem; margin-bottom:4px;">&#128293;</div>
                    <div style="color:#D4520A; font-size:2.2rem; font-weight:900;
                                font-family:'Montserrat',sans-serif;">{hot_count}</div>
                    <div style="color:#5A7080; font-size:0.72rem; text-transform:uppercase;
                                letter-spacing:0.7px; font-weight:700; margin-top:2px;">HOT Leads</div>
                  </div>
                  <div style="background:#FFFFFF; border-radius:16px; padding:1.4rem;
                              text-align:center; border:1px solid #E0D8CF;
                              box-shadow:0 2px 14px rgba(0,0,0,0.07);">
                    <div style="font-size:2rem; margin-bottom:4px;">&#128176;</div>
                    <div style="color:#1C2B3A; font-size:1.45rem; font-weight:900;
                                font-family:'Montserrat',sans-serif;">{q_display}</div>
                    <div style="color:#5A7080; font-size:0.72rem; text-transform:uppercase;
                                letter-spacing:0.7px; font-weight:700; margin-top:2px;">Est. Quote</div>
                  </div>
                  <div style="background:#FFFFFF; border-radius:16px; padding:1.4rem;
                              text-align:center; border:1px solid #E0D8CF;
                              box-shadow:0 2px 14px rgba(0,0,0,0.07);">
                    <div style="font-size:2rem; margin-bottom:4px;">&#128205;</div>
                    <div style="color:#1C2B3A; font-size:1.35rem; font-weight:900;
                                font-family:'Montserrat',sans-serif;">
                      {st.session_state.target_location.split(",")[0]}</div>
                    <div style="color:#5A7080; font-size:0.72rem; text-transform:uppercase;
                                letter-spacing:0.7px; font-weight:700; margin-top:2px;">Location</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

                # ── Download buttons ────────────────────────────────────
                dl1, dl2 = st.columns(2)
                with dl1:
                    pdf_bytes = generate_proposal_pdf(
                        company_name=company_name,
                        location=st.session_state.target_location,
                        leads=lead_lines, analysis=analyzer_raw,
                        quote_range=quote_range, email_draft=outreach_raw,
                        scope_items=extract_scope_items(analyzer_raw),
                    )
                    _safe_loc = re.sub(r"[^A-Za-z0-9_-]", "_", st.session_state.target_location)
                    st.download_button(
                        "📄  Download PDF Proposal", data=pdf_bytes,
                        file_name=f"proposal_{_safe_loc}.pdf",
                        mime="application/pdf",
                    )
                with dl2:
                    export = _json.dumps({
                        "location": st.session_state.target_location, "radius_miles": search_radius,
                        "model": selected_model, "leads": lead_lines, "analysis": analyzer_raw,
                        "quote": quote_range, "email_subject": subject_line, "email_body": outreach_raw,
                    }, indent=2)
                    st.download_button(
                        "⬇️  Download JSON", data=export,
                        file_name=f"leads_{st.session_state.target_location.replace(', ','_')}.json",
                        mime="application/json",
                    )

                # ── Result tabs ─────────────────────────────────────────
                st.markdown("""
                <div style="border-left:5px solid #D4520A; padding-left:14px;
                            margin:1.8rem 0 1rem;">
                  <div style="font-family:'Montserrat',sans-serif; font-weight:800;
                               font-size:1.15rem; color:#1C2B3A;">Agent Results</div>
                </div>""", unsafe_allow_html=True)

                t1, t2, t3, t4 = st.tabs(["🏠  Leads", "🔍  Analysis", "💰  Quote", "📧  Email"])

                with t1:
                    if lead_lines:
                        st.markdown(f"""
                        <div style="display:flex; align-items:center; gap:12px; margin-bottom:1.2rem;">
                          <span style="background:#EEF4FF; color:#2563EB; font-size:0.82rem;
                                       padding:5px 16px; border-radius:50px; font-weight:700;">
                            {len(lead_lines)} leads found</span>
                          <span style="color:#5A7080; font-size:0.88rem; font-weight:500;">
                            {st.session_state.target_location}</span>
                        </div>""", unsafe_allow_html=True)

                        for i, line in enumerate(lead_lines, 1):
                            # Split all sub-lines (Owner: / Contact: can each be on own line)
                            lparts = line.split("\n")
                            main   = lparts[0].lstrip("0123456789.-•) *").strip()
                            owner_line   = ""
                            contact_line = ""
                            for _sl in lparts[1:]:
                                _sl = _sl.strip()
                                if _sl.startswith("Owner:"):
                                    owner_line = _sl
                                elif _sl.startswith("Contact:"):
                                    contact_line = _sl

                            priority = "HOT" if "HOT" in main else ("COLD" if "COLD" in main else "WARM")
                            lc = PRIO_COLORS[priority]

                            seg    = main.split(" — ")
                            addr   = seg[0].strip()
                            detail = " — ".join(seg[1:]).replace(f"Priority: {priority}", "").strip(" —") if len(seg) > 1 else ""

                            # Build info chips — owner row (navy/purple) then agent row (blue/amber/green)
                            chips = []
                            if owner_line.startswith("Owner:"):
                                for op in [p.strip() for p in owner_line[6:].split("|") if p.strip()]:
                                    if op.startswith("Owner:"):
                                        chips.append(f"<span style='background:#E8F0FE;color:#1A3A6A;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;'>&#127968; {_html.escape(op[6:].strip())}</span>")
                                    elif op.startswith("Mail:"):
                                        chips.append(f"<span style='background:#F3EEFF;color:#5B2D8E;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;'>&#128236; {_html.escape(op[5:].strip())}</span>")
                                    elif any(c.isdigit() for c in op):
                                        chips.append(f"<span style='background:#FFF8EC;color:#A06010;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;'>&#128222; {_html.escape(op)}</span>")
                                    elif "@" in op:
                                        chips.append(f"<span style='background:#F0FFF4;color:#1A7A40;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;'>&#9993; {_html.escape(op)}</span>")
                            if contact_line.startswith("Contact:"):
                                for cp in [p.strip() for p in contact_line[8:].split("|") if p.strip()]:
                                    if cp.startswith("Agent:"):
                                        chips.append(f"<span style='background:#EEF4FF;color:#2563EB;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;'>&#128100; {_html.escape(cp[6:].strip())}</span>")
                                    elif "@" in cp:
                                        chips.append(f"<span style='background:#F0FFF4;color:#1A7A40;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;'>&#9993; {_html.escape(cp)}</span>")
                                    elif any(c.isdigit() for c in cp):
                                        chips.append(f"<span style='background:#FFF8EC;color:#A06010;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;'>&#128222; {_html.escape(cp)}</span>")
                                    else:
                                        chips.append(f"<span style='background:#F5F0FF;color:#6A3AA0;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;'>{_html.escape(cp)}</span>")
                            chips_html = (f"<div style='display:flex;flex-wrap:wrap;gap:6px;margin-top:7px;'>{''.join(chips)}</div>") if chips else ""

                            # Single-line HTML string — no blank lines that Markdown would treat as code blocks
                            _card = (
                                f'<div style="background:#FFFFFF;border-radius:12px;padding:14px 18px;'
                                f'border:1px solid #E0D8CF;border-left:5px solid {lc};'
                                f'box-shadow:0 1px 8px rgba(0,0,0,0.06);margin-bottom:10px;">'
                                f'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:14px;">'
                                f'<div style="display:flex;align-items:flex-start;gap:14px;min-width:0;flex:1;">'
                                f'<div style="background:#F2EDE6;border-radius:10px;min-width:34px;height:34px;'
                                f'display:flex;align-items:center;justify-content:center;color:#5A7080;'
                                f'font-size:0.82rem;font-weight:800;font-family:\'Montserrat\',sans-serif;flex-shrink:0;">{i}</div>'
                                f'<div style="min-width:0;flex:1;">'
                                f'<div style="font-weight:700;color:#1C2B3A;font-size:0.94rem;">{_html.escape(addr)}</div>'
                                f'<div style="color:#5A7080;font-size:0.78rem;margin-top:3px;">{_html.escape(detail)}</div>'
                                f'{chips_html}'
                                f'</div></div>'
                                f'<div style="background:{lc};color:#FFFFFF;padding:5px 14px;border-radius:50px;'
                                f'font-size:0.7rem;font-weight:700;letter-spacing:0.6px;flex-shrink:0;'
                                f'margin-top:4px;">{priority}</div>'
                                f'</div></div>'
                            )
                            st.markdown(_card, unsafe_allow_html=True)
                    else:
                        st.info("No structured leads parsed. Check Raw Prospector Output below.")
                        st.markdown(prospector_raw)
                    with st.expander("Raw Prospector Output"):
                        st.text(prospector_raw)

                with t2:
                    st.markdown(analyzer_raw.replace("$", "\\$"))
                    hex_colors = re.findall(r'#([0-9A-Fa-f]{6})', analyzer_raw)
                    if hex_colors:
                        st.markdown("""
                        <div style="border-left:5px solid #D4520A; padding-left:14px;
                                    margin:1.4rem 0 0.8rem;">
                          <div style="font-family:'Montserrat',sans-serif; font-weight:800;
                                      font-size:1rem; color:#1C2B3A;">Detected Colour Palette</div>
                        </div>""", unsafe_allow_html=True)
                        swatches = "".join(
                            f"<div style='display:inline-flex;flex-direction:column;"
                            f"align-items:center;gap:5px;margin:4px 8px;'>"
                            f"<div style='width:54px;height:54px;background:#{c};border-radius:12px;"
                            f"border:2px solid rgba(0,0,0,0.08);box-shadow:0 2px 10px rgba(0,0,0,0.15);'></div>"
                            f"<span style='font-size:0.65rem;color:#5A7080;font-family:monospace;"
                            f"font-weight:600;'>#{c}</span></div>"
                            for c in hex_colors
                        )
                        st.markdown(f"<div style='display:flex;flex-wrap:wrap;'>{swatches}</div>", unsafe_allow_html=True)

                with t3:
                    if isinstance(quote_visual, dict):
                        qr = quote_visual.get("quote_range", "")
                        vd = quote_visual.get("visual_description", "")
                        if qr:
                            lines_qr = qr.splitlines()
                            rest_html = "<br>".join(lines_qr[1:]) if len(lines_qr) > 1 else ""
                            st.markdown(f"""
                            <div style="background:linear-gradient(135deg,#FDF0E0,#FEF8EC);
                                        border:1px solid #F0D080; border-radius:16px;
                                        padding:22px 28px; margin-bottom:1.2rem;">
                              <div style="color:#A06010; font-size:0.72rem; font-weight:700;
                                          text-transform:uppercase; letter-spacing:1.2px;
                                          margin-bottom:8px;">Estimated Quote Range</div>
                              <div style="color:#1C2B3A; font-size:1.8rem; font-weight:900;
                                          font-family:'Montserrat',sans-serif;">
                                {lines_qr[0]}</div>
                              {"<div style='color:#5A7080;font-size:0.88rem;margin-top:10px;line-height:1.7;'>" + rest_html + "</div>" if rest_html else ""}
                            </div>""", unsafe_allow_html=True)
                        if vd:
                            st.markdown(f"""
                            <div style="background:#FFFFFF; border:1px solid #E0D8CF;
                                        border-radius:12px; padding:16px 20px; color:#2A3A4E;
                                        font-size:0.92rem; line-height:1.75;">{_html.escape(vd)}</div>""",
                                unsafe_allow_html=True)
                    st.markdown("""
                    <div style="border-left:5px solid #D4520A; padding-left:14px;
                                margin:1.4rem 0 0.8rem;">
                      <div style="font-family:'Montserrat',sans-serif; font-weight:800;
                                  font-size:1rem; color:#1C2B3A;">Scope of Work</div>
                    </div>""", unsafe_allow_html=True)
                    ai_scope = extract_scope_items(analyzer_raw)
                    for _si, item in enumerate(ai_scope):
                        st.checkbox(item, value=True, key=f"scope_{_si}")

                with t4:
                    st.markdown(f"""
                    <div style="background:#F5F0FF; border:1px solid #D8C8F0; border-radius:12px;
                                padding:14px 20px; margin-bottom:1.2rem;">
                      <div style="color:#6A3AA0; font-size:0.72rem; font-weight:700;
                                  text-transform:uppercase; letter-spacing:1px;">Subject</div>
                      <div style="color:#1C2B3A; font-weight:700; font-size:0.96rem;
                                  margin-top:5px;">{subject_line}</div>
                    </div>""", unsafe_allow_html=True)

                    body_lines = [ln for ln in outreach_raw.splitlines() if not ln.lower().startswith("subject:")]
                    body = "\n".join(body_lines).strip()
                    st.markdown(f"""
                    <div style="background:#FFFFFF; border:1px solid #E0D8CF; border-radius:12px;
                                padding:24px 26px; white-space:pre-wrap; font-family:Georgia,serif;
                                line-height:1.8; max-height:360px; overflow-y:auto;
                                color:#1C2B3A; font-size:0.93rem;">{_html.escape(body)}</div>""",
                        unsafe_allow_html=True)
                    edited_body = st.text_area("Edit before sending:", value=body, height=180, key="outreach_edit")
                    st.markdown("<hr>", unsafe_allow_html=True)
                    ec1, ec2 = st.columns([3, 1])
                    recipient_email = ec1.text_input("Recipient Email", placeholder="homeowner@example.com")
                    approved = ec2.checkbox("Approved to send")
                    if approved and st.button("Send Email", type="primary"):
                        _addr = recipient_email.strip()
                        if not _addr:
                            st.error("Enter a recipient email.")
                        elif "@" not in _addr or "." not in _addr.split("@")[-1]:
                            st.error("Enter a valid email address (e.g. name@example.com).")
                        else:
                            img_path = quote_visual.get("image_path") if isinstance(quote_visual, dict) else None
                            _sent = send_email(edited_body, _addr, img_path, subject=subject_line)
                            if _sent:
                                st.success(f"Email sent to {_addr}")
                    elif not approved:
                        st.caption("Check 'Approved to send' to enable the send button.")

            except Exception as e:
                st.error(f"Workflow error: {e}")
                logger.error(f"Workflow error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — Lead Map
# ─────────────────────────────────────────────────────────────────────────────
with main_tabs[1]:
    st.markdown("""
    <h2 style="margin-bottom:4px;">Lead Map</h2>
    <p style="color:#5A7080; font-size:0.9rem; margin-bottom:1.4rem; font-weight:500;">
      Geocoded via OpenStreetMap (free) — approximately 1 second per address.
    </p>""", unsafe_allow_html=True)

    all_crm_leads = get_all_leads()
    map_source = st.radio("Show leads from:", ["Last run", "All CRM leads"], horizontal=True)

    if map_source == "Last run":
        raw_lines = st.session_state.last_leads
        map_leads = [
            {"address": ln.lstrip("0123456789.-•) *").strip().split(" — ")[0].split(",")[0],
             "priority": "HOT" if "HOT" in ln else ("COLD" if "COLD" in ln else "WARM")}
            for ln in raw_lines
        ]
    else:
        map_leads = [
            {"address": l["address"].lstrip("0123456789.-•) *").strip().split(" — ")[0],
             "priority": "HOT" if "HOT" in l.get("address", "") else ("COLD" if "COLD" in l.get("address", "") else "WARM")}
            for l in all_crm_leads
        ]

    if not map_leads:
        st.markdown("""
        <div style="background:#FFFFFF; border:1px solid #E0D8CF; border-radius:16px;
                    padding:3.5rem; text-align:center;">
          <div style="font-size:3.5rem; margin-bottom:12px;">&#128205;</div>
          <div style="font-weight:800; color:#1C2B3A; font-size:1.15rem; margin-bottom:8px;
                      font-family:'Montserrat',sans-serif;">No leads to map yet</div>
          <div style="color:#5A7080; font-size:0.9rem;">
            Run Lead Generation first to populate the map.
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        with st.spinner(f"Geocoding {len(map_leads)} addresses via OpenStreetMap…"):
            m = build_leads_map(map_leads, st.session_state.target_location)
        st_folium(m, width=None, height=530, returned_objects=[])
        st.markdown("""
        <div style="display:flex; gap:14px; margin-top:14px; flex-wrap:wrap;">
          <div style="display:flex; align-items:center; gap:9px; background:#FFFFFF;
                      border:1px solid #E0D8CF; border-radius:10px; padding:9px 16px;
                      font-size:0.85rem; font-weight:600; color:#1C2B3A;">
            <div style="width:13px;height:13px;background:#D4380D;border-radius:50%;flex-shrink:0;"></div>
            HOT — recently sold / 60+ days listed
          </div>
          <div style="display:flex; align-items:center; gap:9px; background:#FFFFFF;
                      border:1px solid #E0D8CF; border-radius:10px; padding:9px 16px;
                      font-size:0.85rem; font-weight:600; color:#1C2B3A;">
            <div style="width:13px;height:13px;background:#D4870A;border-radius:50%;flex-shrink:0;"></div>
            WARM — moderate indicators
          </div>
          <div style="display:flex; align-items:center; gap:9px; background:#FFFFFF;
                      border:1px solid #E0D8CF; border-radius:10px; padding:9px 16px;
                      font-size:0.85rem; font-weight:600; color:#1C2B3A;">
            <div style="width:13px;height:13px;background:#2563EB;border-radius:50%;flex-shrink:0;"></div>
            COLD — low priority
          </div>
        </div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — CRM Pipeline
# ─────────────────────────────────────────────────────────────────────────────
with main_tabs[2]:
    st.markdown("""
    <h2 style="margin-bottom:1.2rem;">CRM Pipeline</h2>""", unsafe_allow_html=True)

    summary = get_pipeline_summary()
    STATUS_CFG = {
        "New":       ("#2563EB", "#EEF4FF", "&#128203;"),
        "Contacted": ("#D4870A", "#FFF8EC", "&#128222;"),
        "Quoted":    ("#7C3AED", "#F5F0FF", "&#128176;"),
        "Won":       ("#16A34A", "#ECFDF5", "&#127881;"),
        "Lost":      ("#DC2626", "#FEF2F2", "&#10060;"),
    }
    cols = st.columns(len(STATUSES))
    for col, status in zip(cols, STATUSES):
        sc, bg, ico = STATUS_CFG[status]
        cnt = summary.get(status, 0)
        col.markdown(f"""
        <div style="background:{bg}; border:1px solid {sc}30; border-radius:16px;
                    padding:18px 12px; text-align:center; border-top:4px solid {sc};">
          <div style="font-size:1.6rem;">{ico}</div>
          <div style="color:{sc}; font-weight:800; font-size:0.75rem; text-transform:uppercase;
                      letter-spacing:1px; margin:6px 0; font-family:'Montserrat',sans-serif;">
            {status}</div>
          <div style="color:#1C2B3A; font-size:2.1rem; font-weight:900;
                      font-family:'Montserrat',sans-serif;">{cnt}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<hr style='margin:1.4rem 0;'>", unsafe_allow_html=True)
    leads = get_all_leads()

    if not leads:
        st.markdown("""
        <div style="background:#FFFFFF; border:1px solid #E0D8CF; border-radius:16px;
                    padding:3.5rem; text-align:center;">
          <div style="font-size:3.5rem; margin-bottom:12px;">&#128203;</div>
          <div style="font-weight:800; color:#1C2B3A; font-size:1.15rem; margin-bottom:8px;
                      font-family:'Montserrat',sans-serif;">Pipeline is empty</div>
          <div style="color:#5A7080; font-size:0.9rem;">
            Run Lead Generation to auto-populate leads here.
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        fc1, fc2 = st.columns([2, 3])
        filter_status = fc1.selectbox("Filter by status", ["All"] + STATUSES)
        search_term   = fc2.text_input("Search address", placeholder="e.g. Main St")
        filtered = [
            l for l in leads
            if (filter_status == "All" or l["status"] == filter_status)
            and (not search_term or search_term.lower() in l["address"].lower())
        ]
        st.caption(f"Showing {len(filtered)} of {len(leads)} leads")

        for lead in reversed(filtered):
            sc, bg, ico = STATUS_CFG.get(lead["status"], ("#888", "#F5F5F5", "&#11044;"))
            clean_addr  = lead["address"].lstrip("0123456789.-•) *").strip().split(" —")[0].strip()
            with st.container(border=True):
                c1, c2, c3 = st.columns([4, 2, 1])
                c1.markdown(f"""
                <div style="display:flex; align-items:center; gap:12px; padding:4px 0;">
                  <div style="background:{bg}; border:1px solid {sc}40; border-radius:10px;
                              padding:8px 11px; font-size:1.1rem; flex-shrink:0;">{ico}</div>
                  <div>
                    <div style="font-weight:700; color:#1C2B3A; font-size:0.95rem;">
                      {clean_addr}</div>
                    <div style="color:#5A7080; font-size:0.78rem; margin-top:3px; font-weight:500;">
                      {lead.get('location','—')} &nbsp;&middot;&nbsp; Added {lead['created_at'][:10]}
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)

                new_status = c2.selectbox(
                    "Status", STATUSES,
                    index=STATUSES.index(lead["status"]) if lead["status"] in STATUSES else 0,
                    key=f"status_{lead['id']}", label_visibility="collapsed",
                )
                if new_status != lead["status"]:
                    update_lead(lead["address"], status=new_status)
                    st.rerun()

                if c3.button("🗑️", key=f"del_{lead['id']}", help="Delete lead"):
                    delete_lead(lead["address"])
                    st.rerun()

                notes_val = st.text_input(
                    "Notes", value=lead.get("notes", ""),
                    placeholder="Call result, follow-up date, quote sent…",
                    key=f"notes_{lead['id']}", label_visibility="collapsed",
                )
                if notes_val != lead.get("notes", ""):
                    update_lead(lead["address"], notes=notes_val)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — Material Estimator
# ─────────────────────────────────────────────────────────────────────────────
with main_tabs[3]:
    st.markdown("""
    <h2 style="margin-bottom:4px;">Material &amp; Cost Estimator</h2>
    <p style="color:#5A7080; font-size:0.9rem; margin-bottom:1.4rem; font-weight:500;">
      Industry-standard coverage rates &middot; Sherwin-Williams Duration exterior pricing
    </p>""", unsafe_allow_html=True)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#FDF0E0,#FEF8EC); border:1px solid #F0D080;
                border-radius:14px; padding:16px 22px; margin-bottom:1.6rem;
                display:flex; align-items:center; gap:14px;">
      <span style="font-size:1.8rem;">&#128296;</span>
      <div>
        <div style="font-weight:800; color:#A06010; font-size:0.96rem;
                    font-family:'Montserrat',sans-serif;">Quick Quote Calculator</div>
        <div style="color:#6A5020; font-size:0.84rem; margin-top:2px; font-weight:500;">
          Adjust the inputs below — quote updates instantly, no API needed.
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    ic1, ic2, ic3 = st.columns(3)
    sqft    = ic1.number_input("Exterior sq footage", min_value=100, max_value=20000, value=1800, step=100)
    stories = ic2.selectbox("Stories", [1, 2, 3], index=0)
    coats   = ic3.selectbox("Coats of paint", [1, 2], index=1)
    ic4, ic5 = st.columns(2)
    primer   = ic4.checkbox("Include primer coat", value=True)
    prep_lvl = ic5.selectbox("Prep level", ["minimal", "standard", "heavy"], index=1)

    with st.expander("⚙️ Adjust Pricing for Your Market", expanded=False):
        st.caption("Override default prices to match your local suppliers and labour rates.")
        p1, p2, p3, p4 = st.columns(4)
        paint_price  = p1.number_input("Paint $/gal",   min_value=10.0, max_value=300.0, value=55.0,  step=1.0)
        primer_price = p2.number_input("Primer $/gal",  min_value=5.0,  max_value=200.0, value=35.0,  step=1.0)
        labor_rate   = p3.number_input("Labour $/sqft", min_value=0.50, max_value=20.0,  value=1.50,  step=0.05, format="%.2f")
        prep_rate    = p4.number_input("Prep $/sqft",   min_value=0.10, max_value=10.0,  value=0.40,  step=0.05, format="%.2f")

    est = material_estimate(
        sqft=sqft, stories=stories, coats=coats, needs_primer=primer, prep_level=prep_lvl,
        paint_price=paint_price, primer_price=primer_price,
        labor_rate=labor_rate, prep_rate=prep_rate,
    )

    # Big quote banner
    st.markdown(f"""
    <div style="background:linear-gradient(140deg,#1C2B3A 0%,#2C4060 100%);
                border-radius:20px; padding:2rem 2.5rem; margin:1.4rem 0;
                text-align:center; box-shadow:0 6px 28px rgba(28,43,58,0.22);">
      <div style="color:#8AAFCC; font-size:0.75rem; text-transform:uppercase;
                  letter-spacing:2px; font-weight:700; margin-bottom:10px;">
        Recommended Quote Range
      </div>
      <div style="color:#F5A623; font-size:3rem; font-weight:900;
                  font-family:'Montserrat',sans-serif; line-height:1;">
        {est["quote_range"]}
      </div>
      <div style="color:#607A99; font-size:0.88rem; margin-top:10px; font-weight:500;">
        Low: ${est["total_low"]:,} &nbsp;&nbsp;&mdash;&nbsp;&nbsp; High: ${est["total_high"]:,}
      </div>
    </div>

    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:1.4rem;">
      <div style="background:#FFFFFF; border-radius:14px; padding:1.4rem; text-align:center;
                  border:1px solid #E0D8CF; box-shadow:0 2px 10px rgba(0,0,0,0.06);">
        <div style="color:#5A7080; font-size:0.72rem; text-transform:uppercase;
                    letter-spacing:0.8px; font-weight:700; margin-bottom:8px;">Materials</div>
        <div style="color:#1C2B3A; font-size:1.8rem; font-weight:900;
                    font-family:'Montserrat',sans-serif;">${est["materials_cost"]:,}</div>
        <div style="color:#5A7080; font-size:0.78rem; margin-top:6px; font-weight:500;">
          {est["gallons_paint"]} gal paint &middot; {est["gallons_primer"]} gal primer
        </div>
      </div>
      <div style="background:#FFFFFF; border-radius:14px; padding:1.4rem; text-align:center;
                  border:1px solid #E0D8CF; box-shadow:0 2px 10px rgba(0,0,0,0.06);">
        <div style="color:#5A7080; font-size:0.72rem; text-transform:uppercase;
                    letter-spacing:0.8px; font-weight:700; margin-bottom:8px;">Labour</div>
        <div style="color:#1C2B3A; font-size:1.8rem; font-weight:900;
                    font-family:'Montserrat',sans-serif;">${est["labor_cost"]:,}</div>
        <div style="color:#5A7080; font-size:0.78rem; margin-top:6px; font-weight:500;">
          ${labor_rate:.2f}/sqft &middot; {stories} stor{"y" if stories == 1 else "ies"}
        </div>
      </div>
      <div style="background:#FFFFFF; border-radius:14px; padding:1.4rem; text-align:center;
                  border:1px solid #E0D8CF; box-shadow:0 2px 10px rgba(0,0,0,0.06);">
        <div style="color:#5A7080; font-size:0.72rem; text-transform:uppercase;
                    letter-spacing:0.8px; font-weight:700; margin-bottom:8px;">Prep Work</div>
        <div style="color:#1C2B3A; font-size:1.8rem; font-weight:900;
                    font-family:'Montserrat',sans-serif;">${est["prep_cost"]:,}</div>
        <div style="color:#5A7080; font-size:0.78rem; margin-top:6px; font-weight:500;">
          {prep_lvl.title()} prep level
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    summary_txt = (
        f"Exterior Painting Estimate\n"
        f"Sq Footage: {sqft:,} | Stories: {stories} | Coats: {coats}\n"
        f"Prep Level: {prep_lvl.title()}\n"
        f"Paint: {est['gallons_paint']} gal | Primer: {est['gallons_primer']} gal\n"
        f"Materials: ${est['materials_cost']:,} | Labour: ${est['labor_cost']:,} | Prep: ${est['prep_cost']:,}\n"
        f"TOTAL ESTIMATE: {est['quote_range']}"
    )
    st.text_area("Copy for proposal:", value=summary_txt, height=130)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — Photo Assessment
# ─────────────────────────────────────────────────────────────────────────────
with main_tabs[4]:
    st.markdown("""
    <h2 style="margin-bottom:4px;">AI Photo Assessment</h2>
    <p style="color:#5A7080; font-size:0.9rem; margin-bottom:1.4rem; font-weight:500;">
      Upload a house exterior photo — AI assesses paint condition, prep work needed,
      colour suggestions and quote range. Uses Groq Vision (free, no extra key needed).
    </p>""", unsafe_allow_html=True)

    uploaded = st.file_uploader("Upload house exterior photo", type=["jpg", "jpeg", "png", "webp"])

    if uploaded:
        img_bytes = uploaded.read()
        mime_type = f"image/{uploaded.type.split('/')[-1]}" if "/" in uploaded.type else "image/jpeg"
        col_img, col_result = st.columns([1, 1])
        with col_img:
            st.image(img_bytes, caption="Uploaded photo", use_container_width=True)
        with col_result:
            if st.button("🔍  Assess Paint Condition", type="primary"):
                if not os.getenv("GROQ_API_KEY"):
                    st.error("GROQ_API_KEY required for photo assessment.")
                else:
                    from utils.vision_assessment import assess_photo
                    with st.spinner("Analysing with Groq Vision AI…"):
                        assessment = assess_photo(img_bytes, mime_type)
                    if "error" in assessment:
                        st.error(f"Assessment failed: {assessment['error']}")
                    else:
                        cond = assessment.get("condition", "Unknown")
                        prio = assessment.get("priority", "WARM")
                        cc = {"Excellent":"#16A34A","Good":"#22C55E","Fair":"#D4870A",
                              "Poor":"#DC2626","Very Poor":"#991B1B"}.get(cond, "#888888")
                        pc = {"HOT":"#D4380D","WARM":"#D4870A","COLD":"#2563EB"}.get(prio,"#888888")
                        st.markdown(f"""
                        <div style="display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap;">
                          <span style="background:{cc}; color:#FFFFFF; padding:7px 18px;
                                       border-radius:50px; font-weight:700; font-size:0.85rem;">
                            Condition: {cond}</span>
                          <span style="background:{pc}; color:#FFFFFF; padding:7px 18px;
                                       border-radius:50px; font-weight:700; font-size:0.85rem;">
                            Lead: {prio}</span>
                        </div>""", unsafe_allow_html=True)

                        if assessment.get("summary"):
                            st.markdown(f"""
                            <div style="background:#F5F0FF; border:1px solid #D8C8F0;
                                        border-radius:12px; padding:16px 20px; margin-bottom:14px;
                                        color:#1C2B3A; font-size:0.9rem; line-height:1.75;
                                        font-weight:500;">{assessment["summary"]}</div>""",
                                unsafe_allow_html=True)

                        if assessment.get("quote_range"):
                            st.markdown(f"""
                            <div style="background:linear-gradient(135deg,#FDF0E0,#FEF8EC);
                                        border:1px solid #F0D080; border-radius:14px;
                                        padding:16px 22px; margin-bottom:14px;">
                              <div style="color:#A06010; font-size:0.7rem; font-weight:700;
                                          text-transform:uppercase; letter-spacing:1.2px;">
                                Estimated Quote</div>
                              <div style="color:#1C2B3A; font-size:1.6rem; font-weight:900;
                                          font-family:'Montserrat',sans-serif; margin-top:6px;">
                                {assessment["quote_range"]}</div>
                            </div>""", unsafe_allow_html=True)

                        if assessment.get("prep_needed"):
                            st.markdown("""
                            <div style="border-left:5px solid #D4520A; padding-left:14px;
                                        margin:1.2rem 0 0.8rem;">
                              <div style="font-family:'Montserrat',sans-serif; font-weight:800;
                                          font-size:0.96rem; color:#1C2B3A;">Prep Work Needed</div>
                            </div>""", unsafe_allow_html=True)
                            items_html = "".join(
                                f"<div style='display:flex;align-items:center;gap:10px;"
                                f"padding:9px 0;border-bottom:1px solid #F0EBE4;'>"
                                f"<span style='color:#D4520A;font-weight:700;font-size:1rem;'>&#8594;</span>"
                                f"<span style='color:#1C2B3A;font-size:0.9rem;font-weight:500;'>{p}</span>"
                                f"</div>"
                                for p in assessment["prep_needed"]
                            )
                            st.markdown(f"""
                            <div style="background:#FFFFFF; border:1px solid #E0D8CF;
                                        border-radius:12px; padding:12px 18px;">{items_html}
                            </div>""", unsafe_allow_html=True)

                        if assessment.get("color_suggestions"):
                            st.markdown("""
                            <div style="border-left:5px solid #D4520A; padding-left:14px;
                                        margin:1.2rem 0 0.8rem;">
                              <div style="font-family:'Montserrat',sans-serif; font-weight:800;
                                          font-size:0.96rem; color:#1C2B3A;">Colour Suggestions</div>
                            </div>""", unsafe_allow_html=True)
                            for c in assessment["color_suggestions"]:
                                st.markdown(f"""
                                <div style="background:#FFFFFF; border:1px solid #E0D8CF;
                                            border-radius:10px; padding:11px 16px;
                                            margin-bottom:8px; color:#1C2B3A; font-size:0.9rem;
                                            font-weight:500; display:flex; align-items:center; gap:10px;">
                                  <span style="font-size:1.1rem;">&#127912;</span> {c}
                                </div>""", unsafe_allow_html=True)

                        if assessment.get("estimated_sqft"):
                            st.markdown(f"""
                            <div style="background:#F2EDE6; border-radius:10px; padding:10px 16px;
                                        margin-top:10px; color:#5A7080; font-size:0.84rem;
                                        font-weight:600;">
                              Estimated exterior sq footage: ~{assessment["estimated_sqft"]:,} sqft
                            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background:#FFFFFF; border:2px dashed #C8B8A8; border-radius:18px;
                    padding:3.5rem 2rem; text-align:center; margin-bottom:1.6rem;">
          <div style="font-size:4rem; margin-bottom:14px;">&#128247;</div>
          <div style="font-weight:900; color:#1C2B3A; font-size:1.2rem; margin-bottom:10px;
                      font-family:'Montserrat',sans-serif;">Upload a House Exterior Photo</div>
          <div style="color:#5A7080; font-size:0.9rem; max-width:420px;
                      margin:0 auto; line-height:1.8; font-weight:500;">
            The AI will assess paint condition, list prep tasks,
            suggest colour schemes, and estimate the job cost.
            <br><br>
            <em style="color:#7A9080;">Uses your free Groq API key — no extra cost.</em>
          </div>
        </div>

        <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:16px;">
          <div style="background:#FFFFFF; border:1px solid #E0D8CF; border-radius:14px;
                      padding:1.5rem; text-align:center;
                      box-shadow:0 2px 10px rgba(0,0,0,0.05);">
            <div style="font-size:2.2rem; margin-bottom:10px;">&#128269;</div>
            <div style="font-weight:800; color:#1C2B3A; font-size:0.96rem;
                        font-family:'Montserrat',sans-serif;">Condition Assessment</div>
            <div style="color:#5A7080; font-size:0.82rem; margin-top:6px; font-weight:500;">
              Excellent to Very Poor rating
            </div>
          </div>
          <div style="background:#FFFFFF; border:1px solid #E0D8CF; border-radius:14px;
                      padding:1.5rem; text-align:center;
                      box-shadow:0 2px 10px rgba(0,0,0,0.05);">
            <div style="font-size:2.2rem; margin-bottom:10px;">&#127912;</div>
            <div style="font-weight:800; color:#1C2B3A; font-size:0.96rem;
                        font-family:'Montserrat',sans-serif;">Colour Suggestions</div>
            <div style="color:#5A7080; font-size:0.82rem; margin-top:6px; font-weight:500;">
              2–3 tailored colour schemes
            </div>
          </div>
          <div style="background:#FFFFFF; border:1px solid #E0D8CF; border-radius:14px;
                      padding:1.5rem; text-align:center;
                      box-shadow:0 2px 10px rgba(0,0,0,0.05);">
            <div style="font-size:2.2rem; margin-bottom:10px;">&#128176;</div>
            <div style="font-weight:800; color:#1C2B3A; font-size:0.96rem;
                        font-family:'Montserrat',sans-serif;">Instant Quote Range</div>
            <div style="color:#5A7080; font-size:0.82rem; margin-top:6px; font-weight:500;">
              AI-estimated job cost on the spot
            </div>
          </div>
        </div>""", unsafe_allow_html=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:linear-gradient(140deg,#1C2B3A 0%,#0E1A28 100%);
            border-radius:20px; padding:2.2rem; text-align:center; margin-top:3rem;
            box-shadow:0 6px 28px rgba(28,43,58,0.22);">
  <div style="font-size:2.4rem; margin-bottom:10px;">&#127912;</div>
  <div style="color:#F5A623; font-family:'Montserrat',sans-serif; font-weight:900;
              font-size:1.2rem; letter-spacing:-0.3px;">PaintPro AI</div>
  <div style="color:#3D5A78; font-size:0.68rem; letter-spacing:2.5px;
              text-transform:uppercase; margin-top:5px;">Lead Generation Suite</div>
  <div style="color:#3D5A78; font-size:0.82rem; margin-top:16px; line-height:2;
              font-weight:500;">
    Powered by &nbsp;
    <span style="color:#7A9BC8; font-weight:600;">Groq</span> &middot;
    <span style="color:#7A9BC8; font-weight:600;">Cerebras</span> &middot;
    <span style="color:#7A9BC8; font-weight:600;">CrewAI</span> &middot;
    <span style="color:#7A9BC8; font-weight:600;">Streamlit</span>
    &nbsp;&nbsp;|&nbsp;&nbsp;
    <span style="color:#5A7080;">100% Free to Run</span>
  </div>
</div>
""", unsafe_allow_html=True)
