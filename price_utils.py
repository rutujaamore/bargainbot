import re
from rapidfuzz import fuzz


def parse_price(price_str):
    """'₹79,900' -> 79900 (int). Returns None if there's nothing to parse."""
    if not price_str:
        return None
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else None


def find_best_deal(*result_lists):
    """
    Takes any number of ranked result lists (best match first in each,
    e.g. amazon_results, flipkart_results). Compares the TOP match from
    each source by price. Returns (winning_item, is_tie):
      - winning_item: the cheapest match (or the first available item if
        none have a usable price), or None if there's nothing at all.
      - is_tie: True if two or more sources matched the exact same
        lowest price - the UI should say "same price" instead of
        crediting one source as "better" when it isn't.
    """
    top_candidates = [results[0] for results in result_lists if results]

    priced = [c for c in top_candidates if parse_price(c.get("price")) is not None]

    if not priced:
        return (top_candidates[0], False) if top_candidates else (None, False)

    min_price = min(parse_price(c["price"]) for c in priced)
    tied = [c for c in priced if parse_price(c["price"]) == min_price]

    return tied[0], len(tied) > 1


def titles_likely_different_products(title_a, title_b, threshold=55):
    """
    A vague query (no generation/model number, e.g. "OnePlus Nord 5G")
    can legitimately pass the strict filter on both sites while still
    landing on two different real products (Nord 3 vs Nord 5). Rather
    than silently comparing prices as if they're the same item, flag it
    so the UI can warn the person to search with a more specific name.
    """
    if not title_a or not title_b:
        return False
    return fuzz.token_set_ratio(title_a.lower(), title_b.lower()) < threshold
