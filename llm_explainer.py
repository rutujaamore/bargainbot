"""
Turns the FACTS we already calculated (Deal Score, next sale, projected
price) into one natural-sounding sentence, using Groq's free LLM API.

Important design rule, worth being able to explain if asked
--------------------------------------------------------------
The LLM is NEVER given the freedom to invent a number. Every fact in the
prompt (price, score, sale date, discount %, projected price) was already
calculated by real code before this function is even called. The LLM's
only job is turning those facts into a well-phrased sentence - the same
safe pattern the BargainBot reference project uses (its own README
describes the LLM "synthesising" numbers already computed by the ML/
festival layers, not generating them itself).

If the API call fails for ANY reason (no internet, bad key, Groq is
down, request times out), this quietly returns None - the calling code
in prediction.py falls back to the plain rule-based sentence instead of
breaking the page. An LLM call failing should never be able to crash a
price lookup.
"""

import requests

from llm_config import GROQ_API_KEY

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
TIMEOUT_SECONDS = 12


def explain_with_llm(facts):
    """
    facts: dict with the already-calculated numbers, e.g.
        {
            "title": "Samsung Galaxy S24 5G (Marble Gray, 256 GB)",
            "price": 55999,
            "category": "Mobiles",
            "deal_score": 40,
            "confident": True,
            "verdict": "WAIT",
            "next_sale_name": "Big Billion Days / Great Indian Festival",
            "days_away": 50,
            "discount_low": 30,
            "discount_high": 40,
            "projected_price": 36399,
        }

    Returns a plain-English sentence (str), or None if the call failed
    for any reason - caller should fall back to the rule-based text.
    """
    prompt = _build_prompt(facts)

    try:
        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a shopping assistant. Write ONE short, "
                            "natural sentence (max 30 words) explaining a "
                            "buy/wait recommendation to an Indian online "
                            "shopper. Use ONLY the facts given - never "
                            "invent a price, date, or percentage that "
                            "wasn't provided. No markdown, no bullet points, "
                            "just one plain sentence."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 100,
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"].strip()
        return text if text else None

    except Exception:
        # Network issue, bad key, Groq down, unexpected response shape -
        # whatever it is, fail quietly. A missing LLM sentence is fine;
        # a crashed page is not.
        return None


def _build_prompt(facts):
    lines = [
        f"Product: {facts.get('title', 'this product')}",
        f"Category: {facts.get('category', 'Unknown')}",
        f"Current price: Rs.{facts.get('price', 0):,.0f}",
    ]

    if facts.get("confident"):
        lines.append(f"Deal Score: {facts.get('deal_score')}/100 (based on real category price data)")
    else:
        lines.append("Deal Score: not available (not enough real price data for this category/price range)")

    if facts.get("verdict") == "WAIT" and facts.get("next_sale_name"):
        lines.append(
            f"Upcoming sale: {facts['next_sale_name']} in {facts.get('days_away')} days, "
            f"typical discount {facts.get('discount_low')}-{facts.get('discount_high')}%"
        )
        if facts.get("projected_price"):
            lines.append(f"Projected price during that sale: Rs.{facts['projected_price']:,.0f}")
        lines.append("Recommendation: WAIT for the sale")
    else:
        lines.append("Recommendation: BUY NOW (no worthwhile sale close enough)")

    lines.append("\nWrite one natural sentence explaining this recommendation to the shopper.")
    return "\n".join(lines)
