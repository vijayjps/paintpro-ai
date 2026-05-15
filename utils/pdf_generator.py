"""
PDF proposal generator using fpdf2 (free, no API key needed).
Produces a professional painting quote proposal.
"""

import io
from datetime import date
from fpdf import FPDF, XPos, YPos

# Helvetica (built-in) only covers Latin-1. Replace common Unicode chars before writing.
_UNICODE_MAP = str.maketrans({
    "—": "--",   # em dash
    "–": "-",    # en dash
    "‘": "'",    # left single quote
    "’": "'",    # right single quote / apostrophe
    "“": '"',    # left double quote
    "”": '"',    # right double quote
    "•": "-",    # bullet
    "…": "...",  # ellipsis
    " ": " ",    # non-breaking space
    "‒": "-",    # figure dash
    "‐": "-",    # hyphen
    "‑": "-",    # non-breaking hyphen
})


def _s(text: str) -> str:
    """Sanitize text to Latin-1 range safe for Helvetica."""
    if not text:
        return ""
    text = text.translate(_UNICODE_MAP)
    # Drop any remaining chars outside Latin-1 range
    return text.encode("latin-1", errors="replace").decode("latin-1")


class ProposalPDF(FPDF):
    def __init__(self, company_name: str = "Your Painting Company"):
        super().__init__()
        self.company_name = company_name
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_fill_color(30, 90, 160)
        self.rect(0, 0, 210, 22, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 14)
        self.set_xy(10, 6)
        self.cell(0, 10, _s(self.company_name), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(5)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, _s(f"Page {self.page_no()} | {self.company_name} | Generated {date.today()}"), align="C")

    def section_title(self, title: str):
        self.set_fill_color(240, 245, 255)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(30, 90, 160)
        self.cell(0, 8, _s(f"  {title}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def body_text(self, text: str):
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 6, _s(text))
        self.ln(2)

    def key_value(self, key: str, value: str):
        self.set_font("Helvetica", "B", 10)
        self.cell(50, 6, _s(key + ":"), new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 6, _s(value))

    def checklist_item(self, text: str, checked: bool = False):
        self.set_font("Helvetica", "", 10)
        mark = "[x]" if checked else "[ ]"
        self.cell(0, 6, _s(f"  {mark}  {text}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def generate_proposal_pdf(
    company_name: str,
    location: str,
    leads: list[str],
    analysis: str,
    quote_range: str,
    email_draft: str,
    scope_items: list[str] = None,
) -> bytes:
    pdf = ProposalPDF(company_name=company_name)
    pdf.add_page()

    # ── Title block ──────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 90, 160)
    pdf.cell(0, 10, "Painting Proposal", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, _s(f"Target Area: {location}  |  Date: {date.today()}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    # ── Lead list ────────────────────────────────────────────────────────────
    pdf.section_title(f"Identified Leads ({len(leads)})")
    for i, addr in enumerate(leads[:15], 1):
        clean = addr.lstrip("0123456789.-•) *").strip()
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _s(f"  {i}.  {clean}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    # ── Analysis summary ────────────────────────────────────────────────────
    pdf.section_title("Property Analysis")
    # Trim analysis to fit reasonably in PDF
    analysis_text = analysis[:1800].replace("**", "").replace("*", "") if analysis else "See detailed notes."
    pdf.body_text(analysis_text)

    # ── Quote range ─────────────────────────────────────────────────────────
    pdf.section_title("Estimated Quote Range")
    quote_text = quote_range[:800].replace("**", "").replace("*", "") if quote_range else "TBD"
    pdf.set_fill_color(255, 248, 220)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(180, 100, 0)
    pdf.cell(0, 10, _s(f"  {quote_text.splitlines()[0]}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    if len(quote_text.splitlines()) > 1:
        pdf.body_text("\n".join(quote_text.splitlines()[1:]))

    # ── Scope checklist ──────────────────────────────────────────────────────
    pdf.section_title("Scope of Work Checklist")
    _scope = scope_items if scope_items else [
        "Surface preparation & power washing",
        "Primer coat application",
        "Two exterior paint coats",
        "Trim & accent painting",
        "Clean-up & final inspection",
        "Touch-up walkthrough with client",
    ]
    for item in _scope:
        pdf.checklist_item(item)
    pdf.ln(4)

    # ── Outreach email ───────────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Outreach Email Draft")
    email_text = email_draft[:2000].replace("**", "").replace("*", "") if email_draft else ""
    pdf.body_text(email_text)

    # ── Terms & next steps ───────────────────────────────────────────────────
    pdf.section_title("Next Steps")
    for step in [
        "1. Contact homeowner to schedule free color consultation",
        "2. Conduct on-site assessment and finalise quote",
        "3. Send signed proposal and collect deposit",
        "4. Schedule crew and order materials",
        "5. Complete job and collect final payment",
    ]:
        pdf.body_text(step)

    return bytes(pdf.output())
