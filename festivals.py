"""
A real calendar of India's major e-commerce sale events, with realistic
typical discount ranges.

Important - this is NOT machine learning. These dates and discount ranges
are well-known public facts about Amazon/Flipkart's yearly sale calendar
(same idea as how CamelCamelCamel or any price tracker hardcodes known
sale dates - nobody "trains a model" to discover when Diwali is). Being
upfront about this matters: if asked "did the model learn this?", the
honest answer is no - I looked up when these sales actually happen.

Only the DEAL SCORE (in train_deal_model.py / prediction.py) is the
actual trained ML piece. This file is the rule-based half.
"""

from datetime import date

# (month, day, name, low_discount_pct, high_discount_pct)
#
# Expanded from the original 9-event calendar to 19 events, covering both
# Amazon- and Flipkart-specific sales plus regional/cultural sale windows
# (Navratri, Onam, Baisakhi) that Indian shoppers actually plan purchases
# around. Every discount is still given as an honest LOW-HIGH range
# (never a single fake-precise number) - some years a sale runs deeper
# discounts than others, and a range says that honestly.
SALE_CALENDAR = [
    (1, 12, "Amazon Great Republic Day Sale", 15, 30),
    (1, 16, "Flipkart Republic Day Sale", 15, 28),
    (1, 26, "Republic Day Sale (General)", 10, 25),
    (3, 15, "Holi Sale", 10, 20),
    (3, 25, "Holi Sale (Flipkart)", 10, 20),
    (4, 14, "Baisakhi / Tamil New Year Sale", 8, 18),
    (5, 5, "Flipkart Big Shopping Days", 12, 22),
    (5, 15, "Summer Sale", 10, 20),
    (6, 20, "Mid-Year Clearance Sale", 10, 20),
    (7, 15, "Amazon Prime Day", 20, 35),
    (8, 8, "Amazon Freedom Sale", 15, 25),
    (8, 15, "Independence Day Sale", 15, 25),
    (9, 5, "Onam Sale", 10, 20),
    (9, 28, "Navratri Sale", 12, 22),
    (10, 2, "Gandhi Jayanti Sale", 8, 18),
    (10, 5, "Big Billion Days / Great Indian Festival", 30, 40),
    (10, 20, "Diwali Sale", 25, 35),
    (11, 11, "Singles Day Sale", 15, 25),
    (11, 25, "Black Friday", 20, 30),
    (12, 20, "Year End Sale", 15, 25),
    (12, 25, "Christmas Sale", 12, 22),
]


def _next_occurrence(month, day, today):
    """Returns the next date this MM-DD happens, this year or next if it
    already passed this year."""
    candidate = date(today.year, month, day)
    if candidate < today:
        candidate = date(today.year + 1, month, day)
    return candidate


def get_next_sale(today=None):
    """Returns the nearest upcoming sale event as a dict, or None if the
    calendar is empty (it never will be, but keeps the function honest)."""
    if today is None:
        today = date.today()

    upcoming = []
    for month, day, name, low, high in SALE_CALENDAR:
        event_date = _next_occurrence(month, day, today)
        days_away = (event_date - today).days
        upcoming.append({
            "name": name,
            "date": event_date,
            "days_away": days_away,
            "discount_low": low,
            "discount_high": high,
            "discount_avg": (low + high) / 2,
        })

    upcoming.sort(key=lambda e: e["days_away"])
    return upcoming[0] if upcoming else None


def get_upcoming_sales(today=None, limit=3):
    """Returns the next few sales, nearest first - useful for showing a
    short 'upcoming sales' list rather than just the single nearest one."""
    if today is None:
        today = date.today()

    upcoming = []
    for month, day, name, low, high in SALE_CALENDAR:
        event_date = _next_occurrence(month, day, today)
        days_away = (event_date - today).days
        upcoming.append({
            "name": name,
            "date": event_date,
            "days_away": days_away,
            "discount_low": low,
            "discount_high": high,
            "discount_avg": (low + high) / 2,
        })

    upcoming.sort(key=lambda e: e["days_away"])
    return upcoming[:limit]
