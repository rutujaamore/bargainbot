"""
BargainBot - Product Matching

Handles:

1. Amazon/Flipkart search-result filtering
2. Product ranking
3. Amazon vs Flipkart product confidence
4. Variant/specification detection

Important:
- S25 and S25 Ultra are treated as different variants.
- 256GB and 512GB are treated as different configurations.
- Different RAM/storage configurations are reported as variants.
- Colour differences do NOT make products different.
- Long Amazon marketing titles are not heavily penalized.
"""

import re
from rapidfuzz import fuzz


# ============================================================
# TOKENIZER
# ============================================================

TOKEN_RE = re.compile(
    r"\d+\.\d+|[a-z0-9]+"
)


def tokenize(text):
    return TOKEN_RE.findall(
        str(text).lower()
    )


# ============================================================
# ACCESSORY KEYWORDS
# ============================================================

ACCESSORY_KEYWORDS = [
    "charger",
    "case",
    "cover",
    "cable",
    "adapter",
    "screen protector",
    "tempered glass",
    "glass",
    "stand",
    "holder",
    "skin",
    "back cover",
    "pouch",
    "strap",
    "bumper",
    "protector",
]


# ============================================================
# IMPORTANT VARIANT WORDS
# ============================================================

VARIANT_KEYWORDS = [
    "pro",
    "max",
    "plus",
    "ultra",
    "mini",
    "se",
    "lite",
    "ce",
    "fe",
]


# ============================================================
# COMMON BRANDS
# ============================================================

KNOWN_BRANDS = [
    "apple",
    "samsung",
    "oneplus",
    "xiaomi",
    "redmi",
    "realme",
    "oppo",
    "vivo",
    "motorola",
    "google",
    "nothing",
    "iqoo",
    "asus",
    "sony",
    "nokia",
    "hp",
    "dell",
    "lenovo",
    "acer",
    "msi",
    "lg",
]


# ============================================================
# QUERY EXTRACTION
# ============================================================

def extract_query_tokens(product_name):

    query = str(
        product_name or ""
    ).lower().strip()

    words = tokenize(query)

    # 3G / 4G / 5G are not model numbers.
    network_token = re.compile(
        r"^\d+g$"
    )

    filtered_words = [
        word
        for word in words
        if not network_token.match(word)
    ]

    numbers = [
        word
        for word in filtered_words
        if any(
            char.isdigit()
            for char in word
        )
    ]

    brand = ""

    for candidate in KNOWN_BRANDS:

        if candidate in words:

            brand = candidate
            break

    if not brand and words:

        brand = words[0]

    return (
        query,
        words,
        numbers,
        brand
    )


# ============================================================
# ACCESSORY CHECK
# ============================================================

def is_accessory(title_lower):

    return any(
        keyword in title_lower
        for keyword in ACCESSORY_KEYWORDS
    )


# ============================================================
# SEARCH RESULT MATCHING
# ============================================================

def match_products(
    product_name,
    raw_products,
    min_score=55
):
    """
    Filter and rank Amazon/Flipkart search results.

    Returns a list of matching product dictionaries.
    """

    query, words, numbers, brand = (
        extract_query_tokens(
            product_name
        )
    )

    results = []

    for item in raw_products:

        title = str(
            item.get("title", "")
        ).strip()

        if not title or len(title) < 5:
            continue

        title_lower = title.lower()

        # ----------------------------------------------------
        # Remove obvious accessories
        # ----------------------------------------------------

        if is_accessory(title_lower):
            continue

        title_words = set(
            tokenize(title_lower)
        )

        # ----------------------------------------------------
        # Brand check
        # ----------------------------------------------------

        if brand:

            if brand not in title_words:
                continue

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT require every number blindly.
        #
        # This was causing legitimate results such as
        # iPhone 15 256GB to disappear because Amazon and
        # Flipkart format specifications differently.
        # ----------------------------------------------------

        important_numbers = []

        for number in numbers:

            # Ignore network generations.
            if re.match(
                r"^\d+g$",
                number
            ):
                continue

            # Ignore common RAM/storage values here.
            # They are handled by product confidence.
            if re.match(
                r"^\d+(gb|tb)$",
                number
            ):
                continue

            important_numbers.append(
                number
            )

        # ----------------------------------------------------
        # Model numbers:
        #
        # If the search explicitly contains a model number,
        # require it.
        # ----------------------------------------------------

        if important_numbers:

            number_found = any(
                number in title_words
                for number in important_numbers
            )

            if not number_found:
                continue

        # ----------------------------------------------------
        # Variant protection
        #
        # Example:
        #
        # Search: Samsung Galaxy S25
        #
        # Do NOT allow S25 Ultra to become the result.
        # ----------------------------------------------------

        requested_variants = set(
            word
            for word in words
            if word in VARIANT_KEYWORDS
        )

        title_variants = set(
            word
            for word in title_words
            if word in VARIANT_KEYWORDS
        )

        unwanted_variants = (
            title_variants
            - requested_variants
        )

        if unwanted_variants:

            # Don't reject variants for laptop searches
            # where words such as "pro" may occur as
            # processor terminology.
            is_laptop = any(
                word in title_words
                for word in [
                    "laptop",
                    "notebook",
                    "computer"
                ]
            )

            if not is_laptop:
                continue

        # ----------------------------------------------------
        # Fuzzy ranking
        # ----------------------------------------------------

        fuzzy_score = fuzz.token_set_ratio(
            query,
            title_lower
        )

        # ----------------------------------------------------
        # Count important query words
        # ----------------------------------------------------

        matched_words = sum(
            1
            for word in words
            if word in title_words
        )

        word_coverage = (
            matched_words
            / max(len(words), 1)
        )

        # Combined search score.
        score = (
            fuzzy_score * 0.65
            + word_coverage * 100 * 0.35
        )

        if score < min_score:
            continue

        matched_item = dict(item)

        matched_item["score"] = round(
            score,
            1
        )

        results.append(
            matched_item
        )

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results


# ============================================================
# TITLE NORMALIZATION
# ============================================================

def normalize_title(title):

    text = str(
        title or ""
    ).lower()

    replacements = {

        "smartphone": "phone",

        "mobile phone": "phone",

        "mobile": "phone",

        "laptop computer": "laptop",

        "storage": "",

    }

    for old, new in replacements.items():

        text = text.replace(
            old,
            new
        )

    text = re.sub(
        r"[^a-z0-9.]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


# ============================================================
# EXTRACT PRODUCT ATTRIBUTES
# ============================================================

def extract_product_attributes(title):

    text = normalize_title(
        title
    )

    words = tokenize(text)

    attributes = {

        "brand": None,

        "model": None,

        "model_tokens": set(),

        "variant": set(),

        "storage": set(),

        "ram": set(),

        "generation": set(),

        "processor": set(),

        "display": set(),

        "numbers": set(),
    }

    # ========================================================
    # BRAND
    # ========================================================

    for brand in KNOWN_BRANDS:

        if brand in words:

            attributes["brand"] = brand
            break

    # ========================================================
    # STORAGE
    # ========================================================

    storage_matches = re.findall(
        r"\b(\d+(?:\.\d+)?)\s*(gb|tb)\b",
        text
    )

    for value, unit in storage_matches:

        attributes["storage"].add(
            f"{value}{unit}"
        )

    # ========================================================
    # RAM
    # ========================================================

    ram_patterns = [

        r"\b(\d+)\s*gb\s*ram\b",

        r"\b(\d+)\s*gb\s*ddr\d\b",

        r"\b(\d+)\s*gb\s*lpddr\d\b",

    ]

    for pattern in ram_patterns:

        matches = re.findall(
            pattern,
            text
        )

        for value in matches:

            attributes["ram"].add(
                f"{value}gb"
            )

    # ========================================================
    # PROCESSOR
    # ========================================================

    processor_patterns = [

        r"\bcore\s*(?:ultra\s*)?\d+\b",

        r"\b(?:i3|i5|i7|i9)\b",

        r"\bryzen\s*\d+\b",

        r"\bsnapdragon\s*[a-z0-9]+\b",

        r"\bdimensity\s*[a-z0-9]+\b",

        r"\ba\d+\s*(?:pro|max|bionic)?\b",

    ]

    for pattern in processor_patterns:

        matches = re.findall(
            pattern,
            text
        )

        for match in matches:

            attributes["processor"].add(
                re.sub(
                    r"\s+",
                    " ",
                    match
                ).strip()
            )

    # ========================================================
    # INTEL / AMD GENERATION
    # ========================================================

    generation_patterns = [

        r"\b(\d+)(?:st|nd|rd|th)\s*gen\b",

        r"\bgen\s*(\d+)\b",

    ]

    for pattern in generation_patterns:

        matches = re.findall(
            pattern,
            text
        )

        for value in matches:

            attributes["generation"].add(
                value
            )

    # Also recognize Intel model numbers.
    intel_models = re.findall(
        r"\b(?:i3|i5|i7|i9)[-\s]?(\d{4,5}[a-z]{0,2})\b",
        text
    )

    for model in intel_models:

        attributes["processor"].add(
            model
        )

    # ========================================================
    # DISPLAY
    # ========================================================

    display_matches = re.findall(
        r"\b(\d+(?:\.\d+)?)\s*(?:inch|inches|\"|cm)\b",
        text
    )

    for value in display_matches:

        attributes["display"].add(
            value
        )

    # ========================================================
    # VARIANTS
    # ========================================================

    for variant in VARIANT_KEYWORDS:

        if variant in words:

            attributes["variant"].add(
                variant
            )

    # ========================================================
    # MODEL DETECTION
    # ========================================================

    model_patterns = [

        # iPhone 15 / iPhone 15 Pro
        r"\biphone\s+\d+(?:\s+(?:pro|max|plus|mini))?",

        # Samsung Galaxy S25 / S25 Ultra
        r"\bgalaxy\s+[a-z]?\d+(?:\s+(?:ultra|plus|fe|pro))?",

        # OnePlus 13 / OnePlus 13R
        r"\boneplus\s+\d+[a-z]*",

        # HP 15
        r"\bhp\s+\d+[a-z]*",

        # Generic product family
        r"\b[a-z]+\s+\d+[a-z]*",

    ]

    for pattern in model_patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            model = match.group(
                0
            ).strip()

            attributes["model"] = model

            attributes["model_tokens"] = set(
                tokenize(model)
            )

            break

    # ========================================================
    # IMPORTANT NUMBER TOKENS
    # ========================================================

    for word in words:

        if not any(
            char.isdigit()
            for char in word
        ):
            continue

        # Don't treat these as model numbers.
        if word in attributes["storage"]:
            continue

        attributes["numbers"].add(
            word
        )

    return attributes


# ============================================================
# SET COMPARISON
# ============================================================

def compare_sets(
    set_a,
    set_b
):
    """
    Returns:

    1.0 = exact same
    0.8 = overlap
    0.5 = missing information
    0.0 = clearly different
    """

    if not set_a or not set_b:

        return 0.5

    if set_a == set_b:

        return 1.0

    if set_a.intersection(
        set_b
    ):

        return 0.8

    return 0.0


# ============================================================
# MODEL COMPARISON
# ============================================================

def compare_models(
    attr_a,
    attr_b
):
    """
    More intelligent model comparison.

    Handles:

    S25 vs S25
    S25 vs S25 Ultra
    iPhone 15 vs iPhone 15
    OnePlus 13 vs OnePlus 13
    HP 15 vs HP 15
    """

    model_a = attr_a.get(
        "model"
    )

    model_b = attr_b.get(
        "model"
    )

    if not model_a or not model_b:

        return 0.5

    model_a = normalize_title(
        model_a
    )

    model_b = normalize_title(
        model_b
    )

    if model_a == model_b:

        return 1.0

    # One model contained inside another means
    # they may be variants.
    #
    # Example:
    # galaxy s25
    # galaxy s25 ultra
    #

    if (
        model_a in model_b
        or model_b in model_a
    ):

        return 0.35

    fuzzy = fuzz.token_set_ratio(
        model_a,
        model_b
    )

    if fuzzy >= 90:

        return 0.85

    if fuzzy >= 75:

        return 0.65

    return 0.0


# ============================================================
# PRODUCT MATCH CONFIDENCE
# ============================================================

def calculate_match_confidence(
    title_a,
    title_b
):
    """
    Calculate confidence that two listings are the same
    product/configuration.

    Returns integer 0-100.
    """

    if not title_a or not title_b:

        return 0

    attr_a = extract_product_attributes(
        title_a
    )

    attr_b = extract_product_attributes(
        title_b
    )

    # ========================================================
    # BRAND
    # ========================================================

    brand_a = attr_a["brand"]
    brand_b = attr_b["brand"]

    if (
        brand_a
        and brand_b
        and brand_a != brand_b
    ):

        return 10

    if (
        brand_a
        and brand_b
        and brand_a == brand_b
    ):

        brand_score = 1.0

    else:

        brand_score = 0.5

    # ========================================================
    # MODEL
    # ========================================================

    model_score = compare_models(
        attr_a,
        attr_b
    )

    # ========================================================
    # VARIANT
    # ========================================================

    variant_score = compare_sets(
        attr_a["variant"],
        attr_b["variant"]
    )

    # ========================================================
    # STORAGE
    # ========================================================

    storage_score = compare_sets(
        attr_a["storage"],
        attr_b["storage"]
    )

    # ========================================================
    # RAM
    # ========================================================

    ram_score = compare_sets(
        attr_a["ram"],
        attr_b["ram"]
    )

    # ========================================================
    # PROCESSOR
    # ========================================================

    processor_score = compare_sets(
        attr_a["processor"],
        attr_b["processor"]
    )

    # ========================================================
    # GENERATION
    # ========================================================

    generation_score = compare_sets(
        attr_a["generation"],
        attr_b["generation"]
    )

    # ========================================================
    # DISPLAY
    # ========================================================

    display_score = compare_sets(
        attr_a["display"],
        attr_b["display"]
    )

    # ========================================================
    # FUZZY TITLE
    # ========================================================

    normalized_a = normalize_title(
        title_a
    )

    normalized_b = normalize_title(
        title_b
    )

    fuzzy_score = fuzz.token_set_ratio(
        normalized_a,
        normalized_b
    )

    # ========================================================
    # BASE CONFIDENCE
    # ========================================================

    confidence = (

        brand_score * 15

        + model_score * 35

        + variant_score * 15

        + storage_score * 12

        + ram_score * 5

        + processor_score * 8

        + generation_score * 5

        + display_score * 2

        + (fuzzy_score / 100) * 3

    )

    # ========================================================
    # HARD VARIANT RULES
    # ========================================================

    # --------------------------------------------------------
    # S25 vs S25 Ultra
    # --------------------------------------------------------

    if (
        attr_a["model"]
        and attr_b["model"]
    ):

        model_a = normalize_title(
            attr_a["model"]
        )

        model_b = normalize_title(
            attr_b["model"]
        )

        if (
            model_a != model_b
            and (
                model_a in model_b
                or model_b in model_a
            )
        ):

            confidence = min(
                confidence,
                55
            )

    # --------------------------------------------------------
    # Different explicit variants
    # --------------------------------------------------------

    if (
        attr_a["variant"]
        and attr_b["variant"]
        and attr_a["variant"]
        != attr_b["variant"]
    ):

        confidence = min(
            confidence,
            55
        )

    # --------------------------------------------------------
    # Different storage
    # --------------------------------------------------------

    if (
        attr_a["storage"]
        and attr_b["storage"]
        and not attr_a["storage"].intersection(
            attr_b["storage"]
        )
    ):

        confidence = min(
            confidence,
            70
        )

    # --------------------------------------------------------
    # Different RAM
    # --------------------------------------------------------

    if (
        attr_a["ram"]
        and attr_b["ram"]
        and not attr_a["ram"].intersection(
            attr_b["ram"]
        )
    ):

        confidence = min(
            confidence,
            75
        )

    # --------------------------------------------------------
    # Different processor
    # --------------------------------------------------------

    if (
        attr_a["processor"]
        and attr_b["processor"]
        and not attr_a["processor"].intersection(
            attr_b["processor"]
        )
    ):

        confidence = min(
            confidence,
            60
        )

    # --------------------------------------------------------
    # Different generation
    # --------------------------------------------------------

    if (
        attr_a["generation"]
        and attr_b["generation"]
        and attr_a["generation"]
        != attr_b["generation"]
    ):

        confidence = min(
            confidence,
            60
        )

    # ========================================================
    # FINAL VALUE
    # ========================================================

    confidence = round(
        max(
            0,
            min(
                100,
                confidence
            )
        )
    )

    return confidence


# ============================================================
# MATCH DETAILS
# ============================================================

def get_match_details(
    title_a,
    title_b
):
    """
    Return customer-facing match information.
    """

    confidence = calculate_match_confidence(
        title_a,
        title_b
    )

    if confidence >= 85:

        status = "High confidence"
        matched = True

    elif confidence >= 70:

        status = "Good confidence"
        matched = True

    elif confidence >= 55:

        status = "Moderate confidence"
        matched = True

    else:

        status = "Low confidence"
        matched = False

    return {

        "confidence": confidence,

        "matched": matched,

        "status": status,

    }