"""
Material & cost estimator — pure math, zero cost.
All prices are passed in by the caller so painters can adjust for their local market.
"""

# Default prices — used only as fallback when caller passes nothing
DEFAULT_SQFT_PER_GALLON     = 350    # ~350 sqft coverage per gallon (one coat)
DEFAULT_PAINT_PER_GALLON    = 55     # Sherwin-Williams Duration exterior ~$55/gal
DEFAULT_PRIMER_PER_GALLON   = 35     # Primer ~$35/gal
DEFAULT_LABOR_PER_SQFT      = 1.50   # Industry avg exterior labour $1.50/sqft
DEFAULT_PREP_PER_SQFT       = 0.40   # Power wash, scrape, caulk $0.40/sqft


def estimate(
    sqft: int,
    stories: int = 1,
    coats: int = 2,
    needs_primer: bool = True,
    prep_level: str = "standard",       # minimal | standard | heavy
    paint_price: float = DEFAULT_PAINT_PER_GALLON,
    primer_price: float = DEFAULT_PRIMER_PER_GALLON,
    labor_rate: float = DEFAULT_LABOR_PER_SQFT,
    prep_rate: float = DEFAULT_PREP_PER_SQFT,
    sqft_per_gallon: int = DEFAULT_SQFT_PER_GALLON,
) -> dict:
    prep_multiplier = {"minimal": 0.5, "standard": 1.0, "heavy": 1.8}.get(prep_level, 1.0)
    story_factor    = 1.0 + (stories - 1) * 0.25   # +25% per extra storey (scaffolding)

    gallons_paint  = round((sqft / sqft_per_gallon) * coats, 1)
    gallons_primer = round(sqft / sqft_per_gallon, 1) if needs_primer else 0

    materials_cost = (gallons_paint * paint_price + gallons_primer * primer_price)
    labor_cost     = sqft * labor_rate * story_factor
    prep_cost      = sqft * prep_rate  * prep_multiplier * story_factor
    total_low      = round((materials_cost + labor_cost + prep_cost) * 0.90)
    total_high     = round((materials_cost + labor_cost + prep_cost) * 1.15)

    return {
        "sqft":            sqft,
        "stories":         stories,
        "coats":           coats,
        "gallons_paint":   gallons_paint,
        "gallons_primer":  gallons_primer,
        "materials_cost":  round(materials_cost),
        "labor_cost":      round(labor_cost),
        "prep_cost":       round(prep_cost),
        "total_low":       total_low,
        "total_high":      total_high,
        "quote_range":     f"${total_low:,} – ${total_high:,}",
    }


def days_to_peak_season() -> tuple[int, str]:
    """Return (days_away, season_label) for the next painting peak season."""
    from datetime import date
    today = date.today()
    month = today.month
    if 4 <= month <= 9:
        return 0, "Peak painting season NOW (Apr–Sep)"
    next_april = date(today.year + (1 if month > 9 else 0), 4, 1)
    days = (next_april - today).days
    return days, f"Peak season starts in {days} days (April 1)"
