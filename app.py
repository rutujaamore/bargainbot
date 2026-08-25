import os

from flask import Flask, render_template, request
from datetime import datetime

from amazon_scraper import search_amazon_product, get_driver
from flipkart_scraper import search_flipkart_product
from price_utils import find_best_deal, titles_likely_different_products, parse_price
from matcher import get_match_details

import database
import prediction
from scheduler import start_scheduler

app = Flask(__name__)
database.init_db()

# In Flask's debug reloader, the process starts twice (once to watch
# files, once to actually run). WERKZEUG_RUN_MAIN is only set on the
# real run, so this guard stops the background scheduler from starting
# twice and double-checking every alert.
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    start_scheduler()


@app.route("/", methods=["GET", "POST"])
def home():
    amazon_results = []
    flipkart_results = []

    amazon_deal = None
    flipkart_deal = None

    best_deal = None
    best_deal_tied = False

    suggestion = None
    searched_product = None

    errors = []
    mismatch_warning = None

    # New Match Confidence fields
    match_confidence = None
    match_status = None
    same_product = False

    # New real price-history / provenance fields
    history_analysis = None
    history_provenance = None
    history_provenance_level = None
    best_deal_price_int = None

    if request.method == "POST":

        # .strip() so a whitespace-only submission doesn't slip through
        product = (request.form.get("product") or "").strip()

        if product:
            searched_product = product
            driver = None

            try:
                driver = get_driver()

            except Exception as e:
                errors.append(
                    "Couldn't start the browser for scraping. Make sure "
                    f"Google Chrome is installed and try again. ({e})"
                )

            if driver:
                try:

                    # -----------------------------
                    # AMAZON
                    # -----------------------------
                    try:
                        amazon_results = search_amazon_product(
                            product,
                            driver=driver,
                            top_n=1
                        )

                        if amazon_results:
                            database.save_price(
                                product,
                                "amazon",
                                parse_price(
                                    amazon_results[0]["price"]
                                ),
                                amazon_results[0]["title"],
                            )

                    except Exception as e:
                        errors.append(
                            f"Amazon: {e}"
                        )

                    # -----------------------------
                    # FLIPKART
                    # -----------------------------
                    try:
                        flipkart_results = search_flipkart_product(
                            product,
                            driver,
                            top_n=1
                        )

                        if flipkart_results:
                            database.save_price(
                                product,
                                "flipkart",
                                parse_price(
                                    flipkart_results[0]["price"]
                                ),
                                flipkart_results[0]["title"],
                            )

                    except Exception as e:
                        errors.append(
                            f"Flipkart: {e}"
                        )

                finally:
                    try:
                        driver.quit()

                    except Exception:
                        pass

            # ==========================================================
            # DEAL SCORE - AMAZON
            # ==========================================================

            if amazon_results:

                amazon_price = parse_price(
                    amazon_results[0].get("price")
                )

                if amazon_price:

                    try:
                        amazon_deal = prediction.quick_score(
                            amazon_results[0]["title"],
                            amazon_price
                        )

                    except Exception as e:
                        errors.append(
                            f"Prediction (Amazon): {e}"
                        )

            # ==========================================================
            # DEAL SCORE - FLIPKART
            # ==========================================================

            if flipkart_results:

                flipkart_price = parse_price(
                    flipkart_results[0].get("price")
                )

                if flipkart_price:

                    try:
                        flipkart_deal = prediction.quick_score(
                            flipkart_results[0]["title"],
                            flipkart_price
                        )

                    except Exception as e:
                        errors.append(
                            f"Prediction (Flipkart): {e}"
                        )

            # ==========================================================
            # PRODUCT MATCH CONFIDENCE
            # ==========================================================
            #
            # Only calculate this when both stores returned a product.
            #
            # This compares the actual Amazon and Flipkart titles.
            # It does NOT ask the LLM to guess the percentage.
            #

            if amazon_results and flipkart_results:

                amazon_title = amazon_results[0].get(
                    "title",
                    ""
                )

                flipkart_title = flipkart_results[0].get(
                    "title",
                    ""
                )

                try:
                    match_details = get_match_details(
                        amazon_title,
                        flipkart_title
                    )

                    match_confidence = match_details[
                        "confidence"
                    ]

                    match_status = match_details[
                        "status"
                    ]

                    same_product = match_details[
                        "matched"
                    ]

                except Exception as e:
                    errors.append(
                        f"Match Confidence: {e}"
                    )

            # ==========================================================
            # CATEGORY SHARING BETWEEN STORES
            # ==========================================================
            #
            # If both products are actually the same product but one
            # side has category "Other", use the category from the
            # other side.
            #

            if (
                amazon_results
                and flipkart_results
                and same_product
            ):

                if amazon_deal and flipkart_deal:

                    if (
                        amazon_deal["category"] == "Other"
                        and
                        flipkart_deal["category"] != "Other"
                    ):

                        amazon_deal = (
                            prediction.quick_score_with_category(
                                parse_price(
                                    amazon_results[0]["price"]
                                ),
                                flipkart_deal["category"]
                            )
                        )

                    elif (
                        flipkart_deal["category"] == "Other"
                        and
                        amazon_deal["category"] != "Other"
                    ):

                        flipkart_deal = (
                            prediction.quick_score_with_category(
                                parse_price(
                                    flipkart_results[0]["price"]
                                ),
                                amazon_deal["category"]
                            )
                        )

            # ==========================================================
            # BEST STORE / BEST PRICE
            # ==========================================================

            best_deal, best_deal_tied = find_best_deal(
                amazon_results,
                flipkart_results
            )

            best_deal_price_int = None

            if best_deal:
                best_deal_price_int = parse_price(best_deal.get("price"))

            # ==========================================================
            # PRICE PREDICTION
            # ==========================================================

            if best_deal:

                deal_price = parse_price(
                    best_deal.get("price")
                )

                if deal_price:

                    try:
                        suggestion = prediction.generate_suggestion(
                            best_deal["title"],
                            deal_price
                        )

                        print(
                            "[Prediction] reason source:",
                            suggestion.get(
                                "reason_source"
                            )
                        )

                    except Exception as e:
                        errors.append(
                            f"Prediction: {e}"
                        )

            # ==========================================================
            # REAL PRICE HISTORY (honest - never fabricated/forecasted)
            # ==========================================================
            #
            # We only ever show observations that actually came from a
            # real scrape (prices.db). A brand-new search will have a
            # thin or empty history - that's shown honestly via the
            # provenance badge below, not padded out with fake data.
            #

            if best_deal:

                try:
                    history_analysis = database.analyze_product_history(
                        best_deal.get("title"),
                        parse_price(best_deal.get("price"))
                    )

                    record_count = history_analysis["statistics"]["count"]

                    if record_count >= 5:
                        history_provenance = f"Based on {record_count} real price records"
                        history_provenance_level = "good"
                    elif record_count >= 1:
                        history_provenance = (
                            f"Limited data - {record_count} real record"
                            f"{'s' if record_count != 1 else ''} "
                            "(search again over time to build history)"
                        )
                        history_provenance_level = "limited"
                    else:
                        history_provenance = (
                            "No price history yet - this is the first "
                            "time we've seen this exact listing"
                        )
                        history_provenance_level = "none"

                except Exception as e:
                    errors.append(f"History: {e}")

            # ==========================================================
            # MISMATCH WARNING
            # ==========================================================

            if amazon_results and flipkart_results:

                if not same_product:

                    mismatch_warning = (
                        "Amazon and Flipkart's top matches look like "
                        "different products/variants - the price "
                        "comparison above may not be apples-to-apples. "
                        "Try adding the exact model or generation "
                        "number to your search (e.g. 'OnePlus Nord 3 5G' "
                        "instead of 'OnePlus Nord 5G')."
                    )

    # ==============================================================
    # SEND EVERYTHING TO index.html
    # ==============================================================

    return render_template(
        "index.html",

        product=searched_product,

        amazon_results=amazon_results,
        flipkart_results=flipkart_results,

        amazon_deal=amazon_deal,
        flipkart_deal=flipkart_deal,

        best_deal=best_deal,
        best_deal_tied=best_deal_tied,

        suggestion=suggestion,

        errors=errors,
        mismatch_warning=mismatch_warning,

        # New Match Confidence information
        match_confidence=match_confidence,
        match_status=match_status,
        same_product=same_product,

        # New real price-history / provenance information
        history_analysis=history_analysis,
        history_provenance=history_provenance,
        history_provenance_level=history_provenance_level,
        best_deal_price_int=best_deal_price_int,

        alert_message=None,
        alert_error=None,

        time=datetime.now().strftime(
            "%d-%m-%Y %H:%M:%S"
        ),
    )


# ==================================================================
# PRICE ALERT (new)
# ==================================================================
#
# Separate route, separate form on the page - keeps the alert signup
# independent from the main search so a bad alert submission can never
# break the search results above it.
#

@app.route("/set-alert", methods=["POST"])
def set_alert():

    product = (request.form.get("alert_product") or "").strip()
    email = (request.form.get("alert_email") or "").strip()
    target_price_raw = (request.form.get("alert_target_price") or "").strip()

    alert_message = None
    alert_error = None

    try:
        target_price = int(target_price_raw)
    except (TypeError, ValueError):
        target_price = None

    if not product or not email or not target_price or target_price <= 0:
        alert_error = (
            "Please provide a product name, a valid email, and a "
            "target price greater than 0."
        )
    else:
        alert_id = database.create_alert(product, email, target_price)

        if alert_id:
            alert_message = (
                f"Alert set! We'll email {email} when '{product}' "
                f"drops to ₹{target_price:,} or below. "
                f"(Checked every {6} hours in the background.)"
            )
        else:
            alert_error = "Couldn't save that alert - please check the details and try again."

    # Re-render the home page in its empty/default state, plus the
    # alert confirmation - the user came from the same page, so send
    # them back to it rather than a separate confirmation screen.
    return render_template(
        "index.html",

        product=None,
        amazon_results=[],
        flipkart_results=[],
        amazon_deal=None,
        flipkart_deal=None,
        best_deal=None,
        best_deal_tied=False,
        suggestion=None,
        errors=[],
        mismatch_warning=None,
        match_confidence=None,
        match_status=None,
        same_product=False,
        history_analysis=None,
        history_provenance=None,
        history_provenance_level=None,
        best_deal_price_int=None,

        alert_message=alert_message,
        alert_error=alert_error,

        time=datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
    )


if __name__ == "__main__":
    app.run(debug=True)