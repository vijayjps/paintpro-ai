from dotenv import load_dotenv
import os
import sys
import types as _types
import io
import contextlib
import time


def _stub_chromadb():
    """
    Hook into Python's import machinery to intercept EVERY chromadb.* import
    and return an auto-filling stub. No need to list individual submodules.
    Safe because this app uses none of crewai's RAG/knowledge features.
    """
    import importlib.abc
    import importlib.machinery

    class _AutoStub(_types.ModuleType):
        def __getattr__(self, name):
            child = _AutoStub(f"{self.__name__}.{name}")
            setattr(self, name, child)
            return child
        def __call__(self, *a, **kw):
            return _AutoStub("_call_result")
        def __iter__(self):
            return iter([])
        def __bool__(self):
            return False
        def __or__(self, other):
            return self
        def __ror__(self, other):
            return self
        def __and__(self, other):
            return self
        def __class_getitem__(cls, item):
            return cls
        def __mro_entries__(self, bases):  # used as base class: substitute object
            return (object,)
        def __instancecheck__(self, instance):
            return False
        def __subclasscheck__(self, subclass):
            return False

    class _ChromaFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname == "chromadb" or fullname.startswith("chromadb."):
                return importlib.machinery.ModuleSpec(fullname, _ChromaLoader())
            return None

    class _ChromaLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return _AutoStub(spec.name)
        def exec_module(self, module):
            pass

    # Only install once
    if not any(isinstance(f, _ChromaFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _ChromaFinder())
    # Also clear any already-imported real chromadb modules
    for _k in list(sys.modules):
        if _k == "chromadb" or _k.startswith("chromadb."):
            del sys.modules[_k]
from utils.llm_factory import get_llm
from tools.property_scraper import fetch_leads, fetch_recently_sold, format_leads_for_agent, format_recently_sold_for_agent
from tools.web_intelligence import gather_web_intelligence, format_web_intel_for_agent
from tools.commercial_scraper import (
    fetch_osm_commercial, fetch_google_places_commercial, format_commercial_for_agent
)
from tools.contact_lookup import enrich_leads_with_contacts
from tools.county_assessor import enrich_with_assessor

# Enable litellm automatic retry with backoff for rate-limit errors
try:
    import litellm
    litellm.num_retries = 6
    litellm.retry_after = 10   # seconds to wait before first retry
except Exception:
    pass

def _safe_io():
    """Context manager that silences all stdout/stderr writes.
    Prevents 'I/O operation on closed file' when CrewAI's EventBus tries
    to write inside Streamlit's captured stdout environment."""
    return contextlib.ExitStack().__enter__(), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())

class _silence:
    """Context manager: redirect stdout+stderr to /dev/null buffers."""
    def __enter__(self):
        self._old_out = os.dup(1) if hasattr(os, 'dup') else None
        self._buf_out = io.StringIO()
        self._buf_err = io.StringIO()
        self._cm = contextlib.ExitStack()
        self._cm.enter_context(contextlib.redirect_stdout(self._buf_out))
        self._cm.enter_context(contextlib.redirect_stderr(self._buf_err))
        return self
    def __exit__(self, *args):
        self._cm.close()

# Patch CrewAI bug: cache_breakpoint key is left in messages for non-Anthropic providers,
# causing Groq (and others) to reject the request with a 400 validation error.
def _patch_crewai_cache_breakpoint():
    from crewai.llm import LLM
    from crewai.llms.cache import CACHE_BREAKPOINT_KEY

    _original = LLM._format_messages_for_provider

    def _patched(self, messages):
        result = _original(self, messages)
        if not self.is_anthropic:
            for msg in result:
                msg.pop(CACHE_BREAKPOINT_KEY, None)
        return result

    LLM._format_messages_for_provider = _patched

load_dotenv()

# Initialize reusable globals
llm = None
prospector_agent = None
analyzer_agent = None
quote_visual_agent = None
outreach_agent = None
prospect_task = None
analyze_task = None
quote_visual_task = None
outreach_task = None
crew = None
current_provider = None
current_model = None
current_location = None


def initialize_crew(model="llama-3.3-70b-versatile", provider="groq"):
    # Stub chromadb FIRST — must happen before any crewai import touches it
    _stub_chromadb()
    # All crewai imports are lazy here — avoids chromadb/pydantic crash at app startup
    from crewai import Crew, Agent, Task
    from agents.prospector import ProspectorAgent
    from agents.analyzer import AnalyzerAgent
    from agents.quote_visual import QuoteVisualAgent
    from agents.outreach import OutreachAgent
    _patch_crewai_cache_breakpoint()
    global llm, prospector_agent, analyzer_agent, quote_visual_agent, outreach_agent
    global crew, prospect_task, analyze_task, quote_visual_task, outreach_task
    global current_provider, current_model, current_location

    llm = get_llm(provider, model)
    current_provider = provider
    current_model = model
    current_location = None  # will be set in run_crew after task descriptions are applied

    prospector_agent = ProspectorAgent(llm).create_agent()
    analyzer_agent = AnalyzerAgent(llm).create_agent()
    quote_visual_agent = QuoteVisualAgent(llm).create_agent()
    outreach_agent = OutreachAgent(llm).create_agent()

    prospect_task = Task(
        description=f"Find 5-10 potential homes in {os.getenv('TARGET_LOCATION', 'Springfield, IL')} that likely need exterior painting. Focus on older homes, faded paint, or recent real estate listings. Return a list with addresses, brief descriptions, and why they need painting.",
        agent=prospector_agent,
        expected_output="List of potential leads with addresses and reasons."
    )

    analyze_task = Task(
        description=(
            "Using the leads identified by the prospector, analyze the TOP 3 leads in detail. "
            "For each property (residential OR commercial):\n"
            "  - Assess likely paint condition based on age, listing signals, and property type\n"
            "  - Suggest color schemes (residential: curb appeal palettes; commercial: brand-appropriate neutrals)\n"
            "  - Estimate scope: sq footage, surfaces (walls/trim/fascia for homes; full facade/signage areas for commercial)\n"
            "  - Note any special prep work (power washing, priming, scraping)\n"
            "Residential quote range: $2,000-$8,000. Commercial quote range: $8,000-$80,000+."
        ),
        agent=analyzer_agent,
        expected_output="Detailed analysis for top 3 leads: condition, color suggestions, scope, and estimated size of job."
    )

    quote_visual_task = Task(
        description=(
            "Based on the analysis, create a realistic quote range for each of the top 3 leads. "
            "Residential homes: break down materials + labor. "
            "Commercial buildings: include scaffolding, crew size, timeline. "
            "Describe before/after visual concepts (what the property looks like now vs. after painting). "
            "For commercial, describe how fresh paint improves brand image and foot traffic."
        ),
        agent=quote_visual_agent,
        expected_output="Quote range and before/after visual description for each lead, separated by property type."
    )

    outreach_task = Task(
        description=(
            "Write outreach emails for the top leads. Use different tones:\n"
            "  RESIDENTIAL: Warm, personal, neighbor-friendly. Offer free color consultation. "
            "Mention the specific address and what you noticed.\n"
            "  COMMERCIAL (apartments/malls/offices): Professional B2B tone. Address the property manager "
            "or facilities director. Mention ROI (curb appeal → occupancy/foot traffic), "
            "bulk pricing, and minimal disruption scheduling.\n"
            "Write one residential email and one commercial email as examples."
        ),
        agent=outreach_agent,
        expected_output="Two email drafts: one residential (warm/personal) and one commercial (professional B2B), each with subject line and full body."
    )

    crew = Crew(
        agents=[prospector_agent, analyzer_agent, quote_visual_agent, outreach_agent],
        tasks=[prospect_task, analyze_task, quote_visual_task, outreach_task],
        verbose=False,
        cache=False
    )


# Do NOT initialize at import time — Streamlit's stdout isn't ready yet and
# CrewAI's verbose logging causes "I/O operation on closed file". Lazy init
# in run_crew() handles this safely.
crew = None


def run_crew(target_location="Springfield, IL", search_radius=10, model="llama-3.3-70b-versatile", provider="groq"):
    global crew, llm, prospect_task, analyze_task, quote_visual_task, outreach_task
    global current_provider, current_model, current_location

    needs_init = (crew is None or llm is None or
                  provider != current_provider or model != current_model or
                  target_location != current_location)
    if needs_init:
        try:
            with _silence():
                initialize_crew(model=model, provider=provider)
        except Exception as exc:
            return {
                "prospector": f"Fallback: could not initialize crew due to {exc}",
                "analyzer": "Fallback analysis result.",
                "quote_visual": {
                    "quote_range": "$3,500-$4,500",
                    "visual_description": "Before dull, after vibrant.",
                    "image_path": "generated_image_123456.png"
                },
                "outreach": f"Fallback email draft because the Crew runtime could not be initialized: {exc}"
            }

    # Scale lead count and data fetch size based on search radius
    def _radius_scale(r):
        """Returns (ai_min, ai_max, scraper_max, sold_max, ctx_chars) for radius r."""
        if r <= 15:
            return  8, 12, 12,  8, 2500
        elif r <= 40:
            return 12, 18, 20, 12, 3500
        elif r <= 80:
            return 18, 25, 30, 18, 4500
        else:
            return 25, 35, 40, 25, 6000

    _ai_min, _ai_max, _scraper_max, _sold_max, _ctx_chars = _radius_scale(search_radius)

    # Gather all intelligence sources in parallel (residential + commercial + web)
    from concurrent.futures import ThreadPoolExecutor
    _loc_parts = (target_location.split(",") + [""])[:2]
    _city, _state = _loc_parts[0].strip(), _loc_parts[1].strip()
    _google_key = os.getenv("GOOGLE_API_KEY")
    _cse_id     = os.getenv("GOOGLE_CSE_ID")
    _comm_max   = max(10, _scraper_max // 2)   # commercial fetch scales with radius

    with ThreadPoolExecutor(max_workers=5) as ex:
        f_listings    = ex.submit(fetch_leads,                    target_location, search_radius, _scraper_max)
        f_sold        = ex.submit(fetch_recently_sold,            target_location, _sold_max)
        f_intel       = ex.submit(gather_web_intelligence,        _city, _state)
        f_osm         = ex.submit(fetch_osm_commercial,           target_location, search_radius, _comm_max)
        f_google      = ex.submit(fetch_google_places_commercial, target_location, search_radius, _google_key, _comm_max)

    real_listings     = f_listings.result()
    recently_sold     = f_sold.result()
    web_intel         = f_intel.result()
    commercial_osm    = f_osm.result()
    commercial_google = f_google.result()

    # Enrich residential leads: Google Custom Search for contact info (phone/email),
    # then county assessor for authoritative owner name + mailing address.
    if _cse_id:
        real_listings = enrich_leads_with_contacts(real_listings, _google_key, _cse_id, max_lookups=8)
        recently_sold = enrich_leads_with_contacts(recently_sold, _google_key, _cse_id, max_lookups=5)

    # Assessor lookup runs unconditionally (Vision GIS + Patriot Properties need no key;
    # Google CSE tier-3 fallback only fires when _cse_id is set).
    real_listings = enrich_with_assessor(real_listings, _google_key, _cse_id, max_lookups=8)
    recently_sold = enrich_with_assessor(recently_sold, _google_key, _cse_id, max_lookups=5)

    listings_text    = format_leads_for_agent(real_listings)
    sold_text        = format_recently_sold_for_agent(recently_sold)
    intel_text       = format_web_intel_for_agent(web_intel)
    commercial_text  = format_commercial_for_agent(commercial_osm, commercial_google)

    _has_commercial  = bool(commercial_osm or commercial_google)
    _has_residential = bool(real_listings or recently_sold)

    # Compress combined context — wider radius gets more token budget
    combined_full = "\n\n".join(filter(None, [listings_text, sold_text, commercial_text, intel_text]))
    combined = combined_full[:_ctx_chars] if len(combined_full) > _ctx_chars else combined_full

    _lead_range = f"{_ai_min}–{_ai_max}"

    if prospect_task is not None:
        _has_real_data = _has_residential or _has_commercial

        if _has_real_data:
            # Real addresses available from both residential + commercial feeds
            _res_block  = "\n\n".join(filter(None, [listings_text, sold_text]))
            _comm_block = commercial_text
            prospect_task.description = (
                f"CRITICAL: You are working in {target_location} ONLY. "
                f"Use ONLY the real property addresses listed below. Do NOT invent or fabricate any addresses.\n\n"
                + (f"--- RESIDENTIAL (Realtor.com) ---\n{_res_block}\n\n" if _res_block else "")
                + (f"--- COMMERCIAL (OpenStreetMap + Google Places) ---\n{_comm_block}\n\n" if _comm_block else "")
                + f"TASK: From ALL addresses above, select the TOP {_lead_range} painting leads "
                f"(search radius: {search_radius} miles). "
                f"Mix residential AND commercial — aim for at least 30% commercial if available.\n"
                f"For EACH lead provide:\n"
                f"  - Full address exactly as listed above\n"
                f"  - Property type: Residential / Commercial / Industrial / Institutional\n"
                f"  - Why it needs painting (age, condition signals, new owner, high foot traffic)\n"
                f"  - Estimated job size: Small (<$2k) / Medium ($2k-$8k) / Large (>$8k)\n"
                f"  - Lead priority: HOT / WARM / COLD\n"
                f"Format as a numbered list. "
                f"HOT = recently sold, warehouse/industrial, or 60+ days listed."
            )
        # No fabrication fallbacks — if no real data, we return early below.

        current_location = target_location

    # Build address summary for downstream tasks — includes both residential + commercial
    _addr_summary = ""
    _summary_lines = []
    for lead in real_listings[:min(_ai_max, len(real_listings))]:
        _summary_lines.append(f"  - {lead['address']} [Residential]")
    for lead in recently_sold[:min(_sold_max // 2, len(recently_sold))]:
        _summary_lines.append(f"  - {lead['address']} [NEW OWNER — Residential]")
    for lead in (commercial_osm + commercial_google)[:min(_comm_max, _ai_max)]:
        btype = lead.get("building_type", "commercial").replace("_", " ").title()
        _summary_lines.append(f"  - {lead['address']} [{btype} — Commercial]")
    if _summary_lines:
        _addr_summary = f"Properties in {target_location}:\n" + "\n".join(_summary_lines)

    # Apply location-aware task descriptions (also callable after provider fallback)
    def _apply_downstream_descriptions():
        """Re-apply location-aware descriptions to analyze/quote/outreach tasks."""
        if analyze_task is not None:
            analyze_task.description = (
                f"LOCATION: {target_location}. Analyze properties in {target_location} ONLY.\n\n"
                + (f"{_addr_summary}\n\n" if _addr_summary else "")
                + "Analyze the TOP 3 leads. For each property in " + target_location + ":\n"
                "  - Assess paint condition (age, listing signals)\n"
                "  - Suggest color schemes\n"
                "  - Estimate scope: sq footage, surfaces\n"
                "  - Note any special prep work\n"
                "Residential quote range: $2,000-$8,000. Commercial: $8,000-$80,000+."
            )
        if quote_visual_task is not None:
            quote_visual_task.description = (
                f"LOCATION: {target_location}. All quotes are for properties in {target_location}.\n\n"
                + (f"{_addr_summary}\n\n" if _addr_summary else "")
                + "Create a realistic quote range for each of the top 3 leads in "
                + target_location + ". Break down materials + labor for residential. "
                "Include scaffolding, crew size, timeline for commercial. "
                "Describe before/after visual concepts."
            )
        if outreach_task is not None:
            outreach_task.description = (
                f"LOCATION: {target_location}. Write outreach emails for properties in {target_location}.\n\n"
                + (f"{_addr_summary}\n\n" if _addr_summary else "")
                + "Write one residential (warm/personal) and one commercial (professional B2B) "
                "outreach email for leads in " + target_location + ". "
                "Mention specific addresses from the list above."
            )

    _apply_downstream_descriptions()

    def _kickoff_with_fallback():
        """Run the full 4-task crew; auto-retry with Cerebras on Groq daily limit."""
        global crew, llm, current_provider, current_model
        try:
            with _silence():
                return crew.kickoff()
        except Exception as exc:
            err = str(exc)
            if "tokens per day" in err or "TPD" in err:
                cerebras_key = os.getenv("CEREBRAS_API_KEY")
                if cerebras_key:
                    try:
                        with _silence():
                            initialize_crew(model="llama3.1-8b", provider="cerebras")
                        _apply_downstream_descriptions()
                        with _silence():
                            return crew.kickoff()
                    except Exception as cb_exc:
                        raise RuntimeError(
                            f"Groq daily limit reached (100K/day) and Cerebras fallback failed: {cb_exc}"
                        ) from cb_exc
                else:
                    raise RuntimeError(
                        "GROQ_DAILY_LIMIT: Groq free tier limit reached (100,000 tokens/day). "
                        "Add a Cerebras API key (free at cloud.cerebras.ai) in the sidebar "
                        "and switch provider to Cerebras, or wait until midnight UTC for Groq to reset."
                    ) from exc
            raise

    def _kickoff_sub_crew():
        """Run 3-task crew (analyze+quote+outreach); auto-retry with Cerebras on Groq daily limit."""
        def _run():
            from crewai import Crew
            with _silence():
                return Crew(
                    agents=[analyzer_agent, quote_visual_agent, outreach_agent],
                    tasks=[analyze_task, quote_visual_task, outreach_task],
                    verbose=False, cache=False
                ).kickoff()
        try:
            return _run()
        except Exception as exc:
            err = str(exc)
            if "tokens per day" in err or "TPD" in err:
                cerebras_key = os.getenv("CEREBRAS_API_KEY")
                if cerebras_key:
                    try:
                        with _silence():
                            initialize_crew(model="llama3.1-8b", provider="cerebras")
                        _apply_downstream_descriptions()
                        return _run()
                    except Exception as cb_exc:
                        raise RuntimeError(
                            f"Groq daily limit reached (100K/day) and Cerebras fallback failed: {cb_exc}"
                        ) from cb_exc
                else:
                    raise RuntimeError(
                        "GROQ_DAILY_LIMIT: Groq free tier limit reached (100,000 tokens/day). "
                        "Add a Cerebras API key in the sidebar or wait until midnight UTC."
                    ) from exc
            raise

    # ── Early exit when no real data found — never fabricate addresses ──────────
    if not _has_real_data:
        _suggestions = []
        if search_radius < 50:
            _suggestions.append(f"increase radius beyond {search_radius} miles")
        _suggestions.append("try a larger nearby city")
        _suggestions.append("check your internet connection")
        return {
            "prospector": (
                f"NO_REAL_DATA: No verified property data found for "
                f"{target_location} within {search_radius} miles. "
                f"Suggestions: {' / '.join(_suggestions)}."
            ),
            "analyzer":     "",
            "quote_visual": {},
            "outreach":     "",
        }

    # Build prospector text from ALL real scraped data
    lines = [f"Painting leads in {target_location}:\n"]
    idx   = 1
    for lead in real_listings:
        yr      = f", built {lead['year_built']}" if lead.get("year_built") else ""
        days    = f", {lead['days_on_mls']} days listed" if lead.get("days_on_mls") is not None else ""
        price   = f", ${lead['list_price']:,}" if lead.get("list_price") else ""
        style   = f" [{lead['style']}]" if lead.get("style") else ""
        prio    = "HOT" if (lead.get("days_on_mls") or 0) >= 60 else "WARM"
        _cp = []
        if lead.get("agent_name"):  _cp.append(f"Agent: {lead['agent_name']}")
        if lead.get("agent_phone"): _cp.append(lead["agent_phone"])
        if lead.get("agent_email"): _cp.append(lead["agent_email"])
        contact = " | ".join(_cp)
        owner_parts = []
        if lead.get("owner_name"):    owner_parts.append(f"Owner: {lead['owner_name']}")
        if lead.get("owner_address"): owner_parts.append(f"Mail: {lead['owner_address']}")
        if lead.get("owner_phone"):   owner_parts.append(lead["owner_phone"])
        if lead.get("owner_email"):   owner_parts.append(lead["owner_email"])
        owner_line = " | ".join(owner_parts)
        lines.append(
            f"{idx}. {lead['address']}{style}{yr}{days}{price} — Residential — Priority: {prio}"
            + (f"\n   Owner: {owner_line}" if owner_line else "")
            + (f"\n   Contact: {contact}" if contact else "")
        )
        idx += 1
    for lead in recently_sold:
        yr      = f", built {lead['year_built']}" if lead.get("year_built") else ""
        price   = f", sold ${lead['sold_price']:,}" if lead.get("sold_price") else ""
        style   = f" [{lead['style']}]" if lead.get("style") else ""
        _cp = []
        if lead.get("agent_name"):  _cp.append(f"Agent: {lead['agent_name']}")
        if lead.get("agent_phone"): _cp.append(lead["agent_phone"])
        if lead.get("agent_email"): _cp.append(lead["agent_email"])
        contact = " | ".join(_cp)
        owner_parts = []
        if lead.get("owner_name"):    owner_parts.append(f"Owner: {lead['owner_name']}")
        if lead.get("owner_address"): owner_parts.append(f"Mail: {lead['owner_address']}")
        if lead.get("owner_phone"):   owner_parts.append(lead["owner_phone"])
        if lead.get("owner_email"):   owner_parts.append(lead["owner_email"])
        owner_line = " | ".join(owner_parts)
        lines.append(
            f"{idx}. {lead['address']}{style}{yr}{price} [NEW OWNER] — Residential — Priority: HOT"
            + (f"\n   Owner: {owner_line}" if owner_line else "")
            + (f"\n   Contact: {contact}" if contact else "")
        )
        idx += 1
    for lead in (commercial_osm + commercial_google):
        btype   = lead.get("building_type", "commercial").replace("_", " ").title()
        name    = f" [{lead['name']}]" if lead.get("name") else ""
        phone   = f" | Phone: {lead['phone']}" if lead.get("phone") else ""
        prio    = "HOT" if lead.get("score", 0) >= 50 else "WARM"
        lines.append(
            f"{idx}. {lead['address']}{name} — {btype} — Commercial — Priority: {prio}{phone}"
        )
        idx += 1
    prospector_text = "\n".join(lines)

    if _has_real_data:
        # Real addresses available: skip the prospector LLM entirely.
        # Run only analyzer+quote+outreach with real addresses baked into their descriptions.
        try:
            sub_result = _kickoff_sub_crew()
            sub_tasks = sub_result.tasks_output if sub_result and hasattr(sub_result, "tasks_output") else []
            analyzer_text = sub_tasks[0].raw if len(sub_tasks) > 0 else "Analysis unavailable."
            quote_raw     = sub_tasks[1].raw if len(sub_tasks) > 1 else "$3,500-$4,500"
            outreach_text = sub_tasks[2].raw if len(sub_tasks) > 2 else "Email draft unavailable."
        except Exception as exc:
            err = str(exc)
            _daily = "GROQ_DAILY_LIMIT" in err or "tokens per day" in err or "TPD" in err
            analyzer_text = err if _daily else f"Analysis unavailable: {exc}"
            quote_raw     = "$3,500-$4,500"
            outreach_text = err if _daily else "Email draft unavailable."
    # (no else — we returned early above if no real data was found)

    return {
        "prospector": prospector_text,
        "analyzer": analyzer_text,
        "quote_visual": {
            "quote_range": quote_raw,
            "visual_description": "See quote details above.",
            "image_path": "generated_image_123456.png"
        },
        "outreach": outreach_text
    }


if __name__ == "__main__":
    print(run_crew())