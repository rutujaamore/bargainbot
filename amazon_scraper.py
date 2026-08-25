from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import os
import re
import time

from matcher import match_products


# Where debug screenshots are saved if Amazon does not load correctly
DEBUG_DIR = os.path.join(os.path.dirname(__file__), "debug_screenshots")

# Used only for the shortened title shown in the UI.
# The full title is still kept internally for matching.
MAX_TITLE_LENGTH = 150


def get_driver():
    """
    Creates the Chrome driver used by the Amazon and Flipkart scrapers.
    """

    options = webdriver.ChromeOptions()

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")

    options.add_experimental_option(
        "excludeSwitches",
        ["enable-automation"]
    )

    options.add_experimental_option(
        "useAutomationExtension",
        False
    )

    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )

    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )

    except WebDriverException as e:
        raise RuntimeError(
            "Could not start Chrome - make sure Google Chrome is installed "
            f"on this machine. Original error: {e}"
        )

    # Don't allow one page to hang the application forever.
    driver.set_page_load_timeout(30)

    try:
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', "
            "{get: () => undefined})"
        )
    except Exception:
        pass

    return driver


def _save_debug_screenshot(driver, name):
    """
    Saves a screenshot when Amazon behaves unexpectedly.
    """

    os.makedirs(DEBUG_DIR, exist_ok=True)

    path = os.path.join(
        DEBUG_DIR,
        f"{name}.png"
    )

    try:
        driver.save_screenshot(path)
    except WebDriverException:
        return None

    return path


def _dismiss_amazon_popups(driver):
    """
    Attempts to close common Amazon popups.
    """

    try:
        driver.find_element(
            By.CSS_SELECTOR,
            "body"
        ).send_keys("\ue00c")  # ESC

    except WebDriverException:
        pass

    selectors = [
        "#nav-global-location-popover-link",
        "input[name='glowDoneButton']",
    ]

    for selector in selectors:

        try:
            element = driver.find_element(
                By.CSS_SELECTOR,
                selector
            )

            driver.execute_script(
                "arguments[0].click();",
                element
            )

        except Exception:
            pass


def _clean_price_text(price_text):
    """
    Cleans Amazon price text.

    Examples:

        ₹59,999
        ₹59,999.00
        59,999
        59,999.00

    are returned as a clean string such as:

        ₹59,999
    """

    if not price_text:
        return None

    text = str(price_text).strip()

    # Remove whitespace and invisible characters
    text = re.sub(r"\s+", "", text)

    # Must contain a number
    if not re.search(r"\d", text):
        return None

    # Find the first reasonable Indian price number.
    match = re.search(
        r"(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
        text
    )

    if not match:
        return None

    number = match.group(1)

    # Remove decimal .00
    if number.endswith(".00"):
        number = number[:-3]

    # If there is no ₹ symbol, add it.
    return "₹" + number


def _extract_amazon_price(block):
    """
    Amazon uses several different price structures.

    This function tries multiple selectors instead of depending on
    only span.a-price-whole.

    Returns:
        Clean price string such as ₹59,999
        or None if no usable price is available.
    """

    # ---------------------------------------------------------
    # METHOD 1
    # Normal Amazon search-result price
    # ---------------------------------------------------------

    selectors = [
        "span.a-price span.a-offscreen",
        "span.a-price-whole",
        "span.a-price",
        ".a-price .a-offscreen",
    ]

    for selector in selectors:

        try:
            elements = block.select(selector)

            for element in elements:

                text = element.get_text(
                    " ",
                    strip=True
                )

                price = _clean_price_text(text)

                if price:
                    return price

        except Exception:
            pass

    # ---------------------------------------------------------
    # METHOD 2
    # Search directly for a price-like span.
    # ---------------------------------------------------------

    try:

        for span in block.find_all("span"):

            text = span.get_text(
                " ",
                strip=True
            )

            if not text:
                continue

            # Only inspect short text so we don't accidentally
            # treat a long product description as a price.
            if len(text) > 40:
                continue

            if "₹" not in text:
                continue

            price = _clean_price_text(text)

            if price:
                return price

    except Exception:
        pass

    # ---------------------------------------------------------
    # METHOD 3
    # Look for price-like text anywhere inside the result card.
    # ---------------------------------------------------------

    try:

        card_text = block.get_text(
            " ",
            strip=True
        )

        # Prefer values explicitly containing ₹.
        matches = re.findall(
            r"₹\s*[\d,]+(?:\.\d{1,2})?",
            card_text
        )

        for match in matches:

            price = _clean_price_text(match)

            if price:
                return price

    except Exception:
        pass

    return None


def scrape_amazon_raw(product_name, driver):
    """
    Scrapes Amazon search results without applying product matching.

    The scraper collects:

        title
        full_title
        price
        rating
        reviews
        link
        source

    Product filtering/matching is handled separately by matcher.py.
    """

    query = quote_plus(product_name)

    try:

        driver.get(
            f"https://www.amazon.in/s?k={query}"
        )

    except TimeoutException:

        shot = _save_debug_screenshot(
            driver,
            "amazon_page_load_timeout"
        )

        raise RuntimeError(
            "Amazon's search page took too long to load (30s+). "
            "Likely a slow or unstable connection. "
            f"Screenshot saved to: {shot}"
        )

    _dismiss_amazon_popups(driver)

    try:

        WebDriverWait(
            driver,
            15
        ).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div[data-component-type='s-search-result']"
                )
            )
        )

    except TimeoutException:

        shot = _save_debug_screenshot(
            driver,
            "amazon_results_failed"
        )

        raise RuntimeError(
            "Amazon's results page never showed product cards. "
            f"Screenshot saved to: {shot}. "
            "This is often caused by a captcha/bot check or zero results."
        )

    soup = BeautifulSoup(
        driver.page_source,
        "html.parser"
    )

    blocks = soup.find_all(
        "div",
        {
            "data-component-type": "s-search-result"
        }
    )

    raw_products = []

    for block in blocks:

        # -----------------------------------------------------
        # TITLE
        # -----------------------------------------------------

        img = block.find(
            "img",
            alt=True
        )

        full_title = (
            img.get("alt", "").strip()
            if img
            else ""
        )

        link_tag = (
            img.find_parent("a", href=True)
            if img
            else None
        )

        if not link_tag:

            link_tag = (
                block.select_one("a[href*='/dp/']")
                or block.find("a", href=True)
            )

        if not full_title and link_tag:

            full_title = link_tag.get_text(
                " ",
                strip=True
            )

        # Remove Sponsored / Sponsored Ad prefix
        full_title = re.sub(
            r"^sponsored\s*(ad)?\s*[-:]?\s*",
            "",
            full_title,
            flags=re.IGNORECASE
        ).strip()

        # Normalize whitespace
        full_title = re.sub(
            r"\s+",
            " ",
            full_title
        ).strip()

        if not full_title or len(full_title) < 5:
            continue

        # Full title is preserved for matching.
        # Short title is used by the UI.
        display_title = full_title[:MAX_TITLE_LENGTH].strip()

        # -----------------------------------------------------
        # PRICE
        # -----------------------------------------------------

        price = _extract_amazon_price(block)

        # -----------------------------------------------------
        # RATING
        # -----------------------------------------------------

        rating_tag = block.select_one(
            "span.a-icon-alt"
        )

        rating = (
            rating_tag.get_text(strip=True)
            if rating_tag
            else "Not Available"
        )

        # -----------------------------------------------------
        # REVIEWS
        # -----------------------------------------------------

        review_tag = block.select_one(
            "span.a-size-base.s-underline-text"
        )

        reviews = (
            review_tag.get_text(strip=True)
            if review_tag
            else "Not Available"
        )

        # -----------------------------------------------------
        # LINK
        # -----------------------------------------------------

        link = "#"

        if link_tag and link_tag.get("href"):

            href = link_tag["href"]

            if href.startswith("http"):
                link = href
            else:
                link = (
                    "https://www.amazon.in"
                    + href
                )

        # -----------------------------------------------------
        # SAVE PRODUCT
        # -----------------------------------------------------

        raw_products.append(
            {
                # Display title
                "title": display_title,

                # IMPORTANT:
                # Full title is preserved for matching.
                "full_title": full_title,

                "price": price,

                "rating": rating,

                "reviews": reviews,

                "link": link,

                "source": "Amazon",
            }
        )

    # ---------------------------------------------------------
    # DEBUG INFORMATION
    # ---------------------------------------------------------

    print(
        f"[Amazon] result cards found: "
        f"{len(blocks)}, "
        f"titles parsed: {len(raw_products)}"
    )

    for product in raw_products[:5]:

        print(
            f"  - {product['title']}"
        )

        print(
            f"    Price: {product['price']}"
        )

    return raw_products


def search_amazon_product(
    product_name,
    driver=None,
    top_n=5
):
    """
    Searches Amazon and returns ranked matching products.

    Returns an empty list if no sufficiently good match exists.
    """

    product_name = (
        product_name or ""
    ).strip()

    if not product_name:
        return []

    own_driver = driver is None

    if own_driver:
        driver = get_driver()

    matched = []
    raw_products = []

    try:

        # -----------------------------------------------------
        # FIRST ATTEMPT
        # -----------------------------------------------------

        raw_products = scrape_amazon_raw(
            product_name,
            driver
        )

        matched = match_products(
            product_name,
            raw_products
        )[:top_n]

        # -----------------------------------------------------
        # RETRY
        # -----------------------------------------------------

        if not matched:

            print(
                "[Amazon] first attempt found nothing - "
                "retrying once..."
            )

            time.sleep(2)

            raw_products = scrape_amazon_raw(
                product_name,
                driver
            )

            matched = match_products(
                product_name,
                raw_products
            )[:top_n]

    finally:

        if own_driver:

            try:
                driver.quit()
            except Exception:
                pass

    print(
        f"[Amazon] passed strict match filter: "
        f"{len(matched)} / {len(raw_products)}"
    )

    # Helpful debugging:
    # tells us if a matched product exists but its price is missing.
    for product in matched:

        if not product.get("price"):

            print(
                "[Amazon] WARNING: matched product found "
                "but price is unavailable:"
            )

            print(
                f"  - {product.get('title')}"
            )

    return matched