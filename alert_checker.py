"""
The logic the scheduler calls every few hours:

    for each product with a pending (unsent) alert:
        re-scrape it with the SAME Selenium scrapers the live search uses
        save the new price to prices.db (so history keeps growing even
            when nobody is actively searching)
        for each pending alert on that product:
            if the cheapest price found <= alert's target price:
                send the email
                mark the alert as sent

Reuses amazon_scraper.py / flipkart_scraper.py / matcher.py exactly as
they are - no separate "requests"-based scraper, no duplicate matching
logic. One scraping path for the whole app, live search and background
checks alike.
"""

from amazon_scraper import search_amazon_product, get_driver
from flipkart_scraper import search_flipkart_product
from price_utils import parse_price, find_best_deal
from emailer import send_price_alert_email

import database


def check_product(product_name, driver):
    """
    Re-scrapes one product and returns the best (cheapest) matched
    result across Amazon + Flipkart, or None if nothing matched.
    Also saves whatever it finds to prices.db, same as a live search.
    """

    amazon_results = []
    flipkart_results = []

    try:
        amazon_results = search_amazon_product(product_name, driver=driver, top_n=1)

        if amazon_results:
            database.save_price(
                product_name,
                "amazon",
                parse_price(amazon_results[0]["price"]),
                amazon_results[0]["title"],
            )

    except Exception as e:
        print(f"[AlertChecker] Amazon check failed for '{product_name}': {e}")

    try:
        flipkart_results = search_flipkart_product(product_name, driver, top_n=1)

        if flipkart_results:
            database.save_price(
                product_name,
                "flipkart",
                parse_price(flipkart_results[0]["price"]),
                flipkart_results[0]["title"],
            )

    except Exception as e:
        print(f"[AlertChecker] Flipkart check failed for '{product_name}': {e}")

    best_deal, _ = find_best_deal(amazon_results, flipkart_results)
    return best_deal


def check_and_send_alerts():
    """
    Main entry point - called by scheduler.py on each cycle.

    Groups pending alerts by product so each product is only scraped
    ONCE per run, even if five different people are tracking it.
    """

    pending = database.get_pending_alerts()

    if not pending:
        print("[AlertChecker] No pending alerts - nothing to check.")
        return

    tracked_products = sorted(set(alert["product_name"] for alert in pending))

    print(f"[AlertChecker] Checking {len(tracked_products)} tracked product(s)...")

    driver = None

    try:
        driver = get_driver()

        for product_name in tracked_products:

            best_deal = check_product(product_name, driver)

            if not best_deal:
                print(f"[AlertChecker] No match found this run for '{product_name}'.")
                continue

            current_price = parse_price(best_deal.get("price"))

            if current_price is None:
                continue

            matching_alerts = [
                a for a in pending if a["product_name"] == product_name
            ]

            for alert in matching_alerts:

                if current_price <= alert["target_price"]:

                    sent = send_price_alert_email(
                        to_email=alert["email"],
                        product_name=product_name,
                        current_price=current_price,
                        target_price=alert["target_price"],
                        platform=best_deal.get("source"),
                        link=best_deal.get("link"),
                    )

                    if sent:
                        database.mark_alert_sent(alert["id"])

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    print("[AlertChecker] Run complete.")
