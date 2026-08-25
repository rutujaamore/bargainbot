"""
SQLite database for BargainBot.

Stores every real Amazon / Flipkart price found by the scrapers.

This version keeps the original database structure so existing
prices.db data is NOT deleted.

New functionality:
- Product history lookup using the actual scraped title
- Historical minimum / maximum / average
- Recent price trend
- Current price position against history
- Number of historical observations
"""

import sqlite3
import os
from statistics import mean

DB_PATH = os.path.join(
    os.path.dirname(__file__),
    "prices.db"
)


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

def get_connection():
    return sqlite3.connect(DB_PATH)


# ---------------------------------------------------------
# INITIALIZE DATABASE
# ---------------------------------------------------------

def init_db():
    """
    Creates the prices table if it does not already exist.

    Existing data is preserved.
    """

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            platform     TEXT NOT NULL,
            price        INTEGER NOT NULL,
            title        TEXT,
            timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------------------------------------------------------
    # ALERTS TABLE (new)
    # ---------------------------------------------------------
    # One row = one person asking to be emailed when a product's price
    # drops to or below their target. is_sent starts at 0 and flips to 1
    # the moment the scheduler successfully emails them - so we never
    # send the same alert twice for the same target.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            email        TEXT NOT NULL,
            target_price INTEGER NOT NULL,
            is_sent      INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at      TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# CREATE ALERT
# ---------------------------------------------------------

def create_alert(product_name, email, target_price):
    """
    Saves a new price alert request.

    product_name:
        The search term to keep tracking (same format save_price uses,
        so the scheduler can re-search it later).

    email:
        Where to send the notification.

    target_price:
        Alert fires once a scraped price is <= this value.

    Returns the new alert's id, or None if the input was invalid.
    """

    product_name = (product_name or "").lower().strip()
    email = (email or "").strip()

    try:
        target_price = int(target_price)
    except (TypeError, ValueError):
        return None

    if not product_name or not email or target_price <= 0:
        return None

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO alerts (product_name, email, target_price)
        VALUES (?, ?, ?)
        """,
        (product_name, email, target_price)
    )

    conn.commit()
    alert_id = cur.lastrowid
    conn.close()

    return alert_id


# ---------------------------------------------------------
# PENDING ALERTS
# ---------------------------------------------------------

def get_pending_alerts():
    """
    Returns every alert that hasn't been sent yet, so the scheduler
    knows what to check on each run.
    """

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, product_name, email, target_price
        FROM alerts
        WHERE is_sent = 0
        ORDER BY created_at ASC
        """
    )

    rows = cur.fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "product_name": row[1],
            "email": row[2],
            "target_price": row[3],
        }
        for row in rows
    ]


# ---------------------------------------------------------
# MARK ALERT SENT
# ---------------------------------------------------------

def mark_alert_sent(alert_id):
    """
    Flags an alert as sent so it's never emailed twice.
    """

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE alerts
        SET is_sent = 1,
            sent_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (alert_id,)
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# TRACKED PRODUCTS
# ---------------------------------------------------------

def get_tracked_products():
    """
    Returns the distinct list of product search terms that currently
    have at least one pending (unsent) alert - this is what the
    scheduler re-searches on each cycle, instead of re-scraping every
    product anyone has ever searched.
    """

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT DISTINCT product_name
        FROM alerts
        WHERE is_sent = 0
        """
    )

    rows = cur.fetchall()
    conn.close()

    return [row[0] for row in rows]


# ---------------------------------------------------------
# SAVE PRICE
# ---------------------------------------------------------

def save_price(search_term, platform, price, title=None):
    """
    Saves one real price observation.

    search_term:
        What the user typed.

    platform:
        Amazon / Flipkart.

    price:
        Actual scraped price.

    title:
        Actual product title returned by the website.
    """

    if price is None:
        return

    try:
        price = int(price)
    except (TypeError, ValueError):
        return

    if price <= 0:
        return

    search_term = (search_term or "").lower().strip()
    platform = (platform or "").strip()
    title = (title or "").strip()

    if not search_term or not platform:
        return

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO prices
        (
            product_name,
            platform,
            price,
            title
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            search_term,
            platform,
            price,
            title
        )
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# ORIGINAL SEARCH-TERM HISTORY
# ---------------------------------------------------------

def get_history(search_term):
    """
    Returns all saved price records for the exact search term.

    Oldest first.
    """

    search_term = (search_term or "").lower().strip()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            platform,
            price,
            title,
            timestamp
        FROM prices
        WHERE product_name = ?
        ORDER BY timestamp ASC
        """,
        (search_term,)
    )

    rows = cur.fetchall()

    conn.close()

    return [
        {
            "platform": row[0],
            "price": row[1],
            "title": row[2],
            "timestamp": row[3]
        }
        for row in rows
    ]


# ---------------------------------------------------------
# RECORD COUNT
# ---------------------------------------------------------

def get_record_count(search_term):
    """
    Returns the number of observations saved for a search term.
    """

    search_term = (search_term or "").lower().strip()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*)
        FROM prices
        WHERE product_name = ?
        """,
        (search_term,)
    )

    count = cur.fetchone()[0]

    conn.close()

    return count


# ---------------------------------------------------------
# PRODUCT-TITLE HISTORY
# ---------------------------------------------------------

def get_product_history(title, similarity_words=4):
    """
    Finds historical prices for the same product using the scraped
    product title.

    SQLite does not perform fuzzy matching here.

    Instead, we use important words from the title and search for
    previously saved titles containing those words.

    This is intentionally conservative. The final product-matching
    logic remains in matcher.py.
    """

    if not title:
        return []

    title = title.strip()

    # Extract useful words.
    words = title.lower().split()

    # Remove very common words that don't identify the product.
    ignored_words = {
        "the",
        "with",
        "and",
        "for",
        "from",
        "new",
        "latest",
        "official",
        "smartphone",
        "ai",
        "5g",
        "4g",
        "gb",
        "ram",
        "storage"
    }

    useful_words = []

    for word in words:
        cleaned = "".join(
            char for char in word
            if char.isalnum()
        )

        if len(cleaned) >= 3 and cleaned not in ignored_words:
            useful_words.append(cleaned)

    # Keep the first few strong identifying words.
    useful_words = useful_words[:similarity_words]

    if not useful_words:
        return []

    conn = get_connection()
    cur = conn.cursor()

    # Build a parameterized LIKE query.
    conditions = []
    parameters = []

    for word in useful_words:
        conditions.append("LOWER(title) LIKE ?")
        parameters.append(f"%{word}%")

    query = f"""
        SELECT
            platform,
            price,
            title,
            timestamp
        FROM prices
        WHERE {" AND ".join(conditions)}
        ORDER BY timestamp ASC
    """

    cur.execute(query, parameters)

    rows = cur.fetchall()

    conn.close()

    return [
        {
            "platform": row[0],
            "price": row[1],
            "title": row[2],
            "timestamp": row[3]
        }
        for row in rows
    ]


# ---------------------------------------------------------
# EXACT PRODUCT HISTORY
# ---------------------------------------------------------

def get_exact_product_history(title):
    """
    Gets historical observations where the saved scraped title
    exactly matches the current title.

    This is the safest history lookup.

    We will use this before broader matching.
    """

    if not title:
        return []

    title = title.strip()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            platform,
            price,
            title,
            timestamp
        FROM prices
        WHERE LOWER(title) = LOWER(?)
        ORDER BY timestamp ASC
        """,
        (title,)
    )

    rows = cur.fetchall()

    conn.close()

    return [
        {
            "platform": row[0],
            "price": row[1],
            "title": row[2],
            "timestamp": row[3]
        }
        for row in rows
    ]


# ---------------------------------------------------------
# HISTORICAL STATISTICS
# ---------------------------------------------------------

def get_price_statistics(history):
    """
    Calculates transparent statistics from historical observations.

    Returns:

        count
        minimum
        maximum
        average
        latest
        first
        price_change
        price_change_percent
    """

    if not history:
        return {
            "count": 0,
            "minimum": None,
            "maximum": None,
            "average": None,
            "latest": None,
            "first": None,
            "price_change": None,
            "price_change_percent": None
        }

    prices = [
        item["price"]
        for item in history
        if item.get("price") is not None
        and item["price"] > 0
    ]

    if not prices:
        return {
            "count": 0,
            "minimum": None,
            "maximum": None,
            "average": None,
            "latest": None,
            "first": None,
            "price_change": None,
            "price_change_percent": None
        }

    first_price = prices[0]
    latest_price = prices[-1]

    price_change = latest_price - first_price

    if first_price > 0:
        price_change_percent = round(
            (price_change / first_price) * 100,
            2
        )
    else:
        price_change_percent = None

    return {
        "count": len(prices),

        "minimum": min(prices),

        "maximum": max(prices),

        "average": round(
            mean(prices),
            2
        ),

        "latest": latest_price,

        "first": first_price,

        "price_change": price_change,

        "price_change_percent": price_change_percent
    }


# ---------------------------------------------------------
# CURRENT PRICE VS HISTORY
# ---------------------------------------------------------

def analyze_current_price(current_price, history):
    """
    Compares the current price with historical observations.

    This function does NOT predict the future.

    It only answers:

        Is today's price close to the historical low?
        Is it below/above the historical average?
        How far is it from the historical minimum?
    """

    if current_price is None or current_price <= 0:
        return {
            "available": False
        }

    stats = get_price_statistics(history)

    if stats["count"] == 0:
        return {
            "available": False
        }

    minimum = stats["minimum"]
    maximum = stats["maximum"]
    average = stats["average"]

    distance_from_minimum = current_price - minimum

    if minimum > 0:
        distance_from_minimum_percent = round(
            (distance_from_minimum / minimum) * 100,
            2
        )
    else:
        distance_from_minimum_percent = None

    if average > 0:
        difference_from_average_percent = round(
            ((current_price - average) / average) * 100,
            2
        )
    else:
        difference_from_average_percent = None

    # Where current price sits between historical minimum and maximum.
    if maximum != minimum:
        position_percent = round(
            (
                (current_price - minimum)
                /
                (maximum - minimum)
            ) * 100,
            2
        )

        position_percent = max(
            0,
            min(100, position_percent)
        )
    else:
        position_percent = 0

    return {
        "available": True,

        "history_count": stats["count"],

        "historical_minimum": minimum,

        "historical_maximum": maximum,

        "historical_average": average,

        "current_price": current_price,

        "distance_from_minimum": distance_from_minimum,

        "distance_from_minimum_percent":
            distance_from_minimum_percent,

        "difference_from_average_percent":
            difference_from_average_percent,

        "historical_position_percent":
            position_percent
    }


# ---------------------------------------------------------
# PRICE TREND
# ---------------------------------------------------------

def get_price_trend(history):
    """
    Gives a simple transparent trend based on the first and latest
    observations.

    This is NOT machine learning.

    Possible results:

        FALLING
        RISING
        STABLE
        INSUFFICIENT_DATA
    """

    if not history or len(history) < 2:
        return {
            "trend": "INSUFFICIENT_DATA",
            "change_percent": None
        }

    prices = [
        item["price"]
        for item in history
        if item.get("price") is not None
        and item["price"] > 0
    ]

    if len(prices) < 2:
        return {
            "trend": "INSUFFICIENT_DATA",
            "change_percent": None
        }

    first_price = prices[0]
    latest_price = prices[-1]

    if first_price <= 0:
        return {
            "trend": "INSUFFICIENT_DATA",
            "change_percent": None
        }

    change_percent = round(
        ((latest_price - first_price) / first_price) * 100,
        2
    )

    # Small changes are treated as stable.
    if change_percent <= -3:
        trend = "FALLING"

    elif change_percent >= 3:
        trend = "RISING"

    else:
        trend = "STABLE"

    return {
        "trend": trend,
        "change_percent": change_percent
    }


# ---------------------------------------------------------
# COMPLETE PRODUCT ANALYSIS
# ---------------------------------------------------------

def analyze_product_history(title, current_price):
    """
    Main helper for the future price_predictor.py.

    It first tries exact title history.

    If there is not enough exact history, it tries the more flexible
    product-title lookup.

    Returns all useful historical information in one dictionary.
    """

    if not title or current_price is None:
        return {
            "available": False,
            "history": [],
            "statistics": {},
            "current_analysis": {},
            "trend": {}
        }

    # First: safest lookup.
    history = get_exact_product_history(title)

    # If exact title has insufficient history, use broader title lookup.
    if len(history) < 2:
        broader_history = get_product_history(title)

        if len(broader_history) > len(history):
            history = broader_history

    statistics = get_price_statistics(history)

    current_analysis = analyze_current_price(
        current_price,
        history
    )

    trend = get_price_trend(history)

    return {
        "available": len(history) > 0,

        "history": history,

        "statistics": statistics,

        "current_analysis": current_analysis,

        "trend": trend
    }