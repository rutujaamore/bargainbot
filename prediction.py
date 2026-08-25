"""
Turns (product title, live price) into a Deal Score + a Buy Now / Wait
suggestion, by combining two honestly-separate things:

1. Deal Score - genuinely trained (train_deal_model.py, scikit-learn,
   real Amazon India category price data). Answers: "is this price good
   for this category?"

2. Festival calendar (festivals.py) - rule-based, real known sale dates.
   Answers: "is a sale coming up, and roughly how much off?"

The verdict below is a simple, transparent rule combining both - not a
model. Worth being able to say exactly that if asked.

IMPORTANT LIMITATION, fixed here on purpose
--------------------------------------------
The Amazon training data is dominated by cheap accessories (earbuds,
cables) - so a real phone (₹50,000+) or appliance will always look
"wildly overpriced" against that baseline, even when the price is
completely normal. Rather than show a falsely confident low score for
these cases, score_deal() now checks whether the price is actually
within a range this category's training data can speak to, and returns
confident=False when it can't - the UI shows "not enough data" instead
of a misleading number.
"""

import json
import math
import os
import re

MODEL_PATH = os.path.join(os.path.dirname(__file__), "deal_model.json")

# Simple keyword rules to guess a category from a scraped product title.
# This is the only signal we can extract from a live scrape (no category
# field comes back from Amazon/Flipkart's search cards) - so this keyword
# map is doing an honest, visible job rather than a hidden ML classifier.
# "Mobiles" and "Laptops" are checked FIRST and deliberately kept separate
# from "Electronics"/"Computers&Accessories" - those two have their own
# dedicated real-price datasets now, so a phone/laptop search should never
# fall into the general bucket that's dominated by cheap accessories.
CATEGORY_KEYWORDS = {
    "Mobiles": [
        "phone", "iphone", "galaxy", "redmi", "oneplus", "realme", "vivo",
        "oppo", "poco", "nokia", "motorola", "asus rog phone", "iqoo",
        "smartphone",
    ],
    "Laptops": [
        "laptop", "notebook computer", "macbook", "chromebook", "ultrabook",
        "gaming laptop",
    ],
    # Split out of the old catch-all "Electronics" bucket - each of these
    # has 60+ real samples of its own (see train_deal_model.py), so they
    # get their own honest typical price instead of being judged against
    # a bucket dominated by ~Rs.200 cables and earbuds.
    "Televisions": [
        "tv", "television", "smart tv", "led tv", "oled tv", "qled",
    ],
    "Wearables": [
        "smartwatch", "smart watch", "fitness band", "fitness tracker",
    ],
    "Headphones&Earbuds": [
        "earbud", "headphone", "airpods", "earphone", "neckband",
    ],
    "Electronics": [
        "camera", "speaker", "watch", "tablet", "ipad",
    ],
    "Computers&Accessories": [
        "keyboard", "mouse", "monitor", "cable", "charger", "adapter",
        "pendrive", "ssd", "hard disk", "webcam", "router",
    ],
    "Home&Kitchen": [
        "mixer", "grinder", "cooker", "kettle", "fan", "iron", "vacuum",
        "furniture", "mattress", "blender", "toaster", "microwave",
        "oven", "washing machine", "refrigerator", "fridge", "geyser",
        "water heater", "dishwasher", "chimney", "air conditioner",
        "split ac", "inverter ac", "air cooler",
    ],
    "OfficeProducts": [
        "pen", "notebook diary", "stapler", "printer", "ink", "desk",
        "chair",
    ],
}


# A category's score is only trustworthy if it was trained on enough real
# samples AND the price we're checking isn't wildly outside what that
# training data actually covered.
MIN_SAMPLES_FOR_CONFIDENCE = 30
MAX_Z_FOR_CONFIDENCE = 2.0


def infer_category(title):
    """Guesses a category from a product title using simple keyword
    matching. Falls back to 'Other' if nothing matches - honest default
    rather than a forced guess. Matches each keyword starting at a word
    boundary (so "iron" can't falsely match inside "Inspiron") but allows
    trailing letters after it (so "earbud" still matches "Earbuds")."""
    title_lower = title.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\w*\b", title_lower):
                return category
    return "Other"


def _load_model():
    with open(MODEL_PATH) as f:
        return json.load(f)


def score_deal(price, category):
    """Returns {score, confident, z, typical_price}. score is 0-100 (~50 =
    about average for the category, higher = cheaper than typical, lower =
    pricier). typical_price is the real category average in rupees, so the
    UI can show WHY a score is what it is (e.g. "typical Mobiles price is
    ₹37,528 - this is a premium flagship, priced above average, which is
    normal for that segment") instead of a bare unexplained number.
    confident is False when this price is higher than anything actually
    observed in this category's real training data (or the category
    itself had too few samples to trust) - in that case, the UI should
    say so instead of displaying the (extrapolated) number."""
    model = _load_model()
    stats = model["categories"].get(category, model["categories"].get("Other"))

    if not stats or price <= 0:
        return {"score": None, "confident": False, "z": None, "typical_price": None}

    log_price = math.log(price)
    z = (log_price - stats["log_mean_price"]) / stats["std"]
    score = round(max(0, min(100, 50 - (z * 20))))

    # Confidence is about whether we've genuinely SEEN prices like this
    # before, not just a statistical distance from the average - a 20%
    # buffer above the real observed max allows near-max prices some
    # slack without pretending we can judge something far beyond
    # anything in the training data.
    within_seen_range = price <= stats["max_price"] * 1.2
    confident = stats["sample_count"] >= MIN_SAMPLES_FOR_CONFIDENCE and within_seen_range

    return {
        "score": score,
        "confident": confident,
        "z": round(z, 2),
        "typical_price": round(stats["typical_price"]),
    }


def quick_score_with_category(price, category):
    """Same as quick_score(), but for when the category is already known
    (borrowed from the other site's matching product) instead of guessed
    from this title."""
    deal = score_deal(price, category)
    return {
        "category": category,
        "deal_score": deal["score"],
        "confident": deal["confident"],
        "typical_price": deal["typical_price"],
    }


def quick_score(title, price):
    """Lightweight version of generate_suggestion() - just the category +
    Deal Score, no festival reasoning. Used to show a score on EACH
    source's card (Amazon AND Flipkart), not just the winning price -
    the Deal Score answers 'is this price good for this category', which
    is a fair question regardless of which site the price came from."""
    category = infer_category(title)
    deal = score_deal(price, category)
    return {
        "category": category,
        "deal_score": deal["score"],
        "confident": deal["confident"],
        "typical_price": deal["typical_price"],
    }


def generate_suggestion(title, price):
    """Main entry point - returns a dict the UI can render directly."""
    from festivals import get_next_sale, get_upcoming_sales

    category = infer_category(title)
    deal = score_deal(price, category)
    next_sale = get_next_sale()
    upcoming_sales = get_upcoming_sales(limit=3)

    # The project's whole premise is predicting the next 3 MONTHS - so the
    # window for "is a sale worth waiting for" should match that, not an
    # arbitrary shorter number. A sale anywhere in the next 90 days counts,
    # unless today's price is already excellent (handled below).
    SALE_WINDOW_DAYS = 90
    sale_is_close = next_sale and next_sale["days_away"] <= SALE_WINDOW_DAYS

    if sale_is_close and (not deal["confident"] or deal["score"] < 75):
        # A real sale is close, and we either can't confidently say this
        # price is already great, or we CAN confidently say it isn't -
        # either way, waiting for a known sale is the safer suggestion.
        projected_price = round(price * (1 - next_sale["discount_avg"] / 100))
        verdict = "WAIT"
        reason = (
            f"{next_sale['name']} is in {next_sale['days_away']} days, with "
            f"typical discounts of {next_sale['discount_low']}-{next_sale['discount_high']}% "
            f"on {category.replace('&', ' & ')} products. Price could drop to "
            f"around ₹{projected_price:,}."
        )
    elif deal["confident"] and deal["score"] >= 75:
        verdict = "BUY_NOW"
        projected_price = None
        reason = (
            f"This price is already well below the typical price for "
            f"{category.replace('&', ' & ')} products - no need to wait."
        )
    elif not deal["confident"]:
        verdict = "BUY_NOW"
        projected_price = None
        reason = (
            "No major sale is close enough to be worth waiting for right now. "
            "(Deal Score skipped - my training data doesn't have enough real "
            f"{category.replace('&', ' & ')} products priced this high to judge "
            "it confidently. Works best under roughly ₹15,000.)"
        )
    else:
        verdict = "BUY_NOW"
        projected_price = None
        reason = "No major sale is close enough to be worth waiting for right now."

    # Everything above is real, calculated fact - the LLM is only asked to
    # phrase it nicely. If it fails for any reason, the rule-based
    # `reason` above is already a complete, correct fallback.
    reason_source = "rule-based"
    try:
        from llm_explainer import explain_with_llm

        facts = {
            "title": title,
            "price": price,
            "category": category,
            "deal_score": deal["score"],
            "confident": deal["confident"],
            "verdict": verdict,
            "next_sale_name": next_sale["name"] if (verdict == "WAIT" and next_sale) else None,
            "days_away": next_sale["days_away"] if (verdict == "WAIT" and next_sale) else None,
            "discount_low": next_sale["discount_low"] if (verdict == "WAIT" and next_sale) else None,
            "discount_high": next_sale["discount_high"] if (verdict == "WAIT" and next_sale) else None,
            "projected_price": projected_price,
        }
        llm_reason = explain_with_llm(facts)
        if llm_reason:
            reason = llm_reason
            reason_source = "llm"
    except Exception:
        pass  # keep the rule-based reason - never let this break the page

    return {
        "category": category,
        "deal_score": deal["score"],
        "confident": deal["confident"],
        "typical_price": deal["typical_price"],
        "verdict": verdict,
        "reason": reason,
        "reason_source": reason_source,
        "projected_price": projected_price,
        "next_sale": next_sale,
        "upcoming_sales": upcoming_sales,
    }
