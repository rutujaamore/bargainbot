from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import re
import time

from matcher import match_products
from amazon_scraper import _save_debug_screenshot

PRICE_PATTERN = re.compile(r"₹[\d,]+")
MAX_TITLE_LENGTH = 150


def scrape_flipkart_raw(product_name, driver):
    """
    Scrape Flipkart search results.

    Important:
    Flipkart can take a long time to finish loading because of images,
    JavaScript and other resources. We don't need the entire page to
    finish loading - we only need the product cards.
    """

    query = quote_plus(product_name)
    url = f"https://www.flipkart.com/search?q={query}"

    # ---------------------------------------------------------
    # 1. Navigate to Flipkart
    # ---------------------------------------------------------
    try:
        driver.get(url)

    except TimeoutException:
        # IMPORTANT:
        # Selenium may timeout while the useful product cards have
        # already loaded. Do NOT immediately fail.
        print("[Flipkart] Page load timed out - checking loaded page...")

    except WebDriverException as e:
        shot = _save_debug_screenshot(
            driver,
            "flipkart_navigation_failed"
        )

        raise RuntimeError(
            "Flipkart page could not be loaded. "
            f"Screenshot saved to: {shot}. Error: {e}"
        )

    # Give Flipkart a small amount of time to render its JS content.
    time.sleep(2)

    # ---------------------------------------------------------
    # 2. Close Login popup if present
    # ---------------------------------------------------------
    try:
        login_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "button._2KpZ6l._2doB4z"
                )
            )
        )

        driver.execute_script(
            "arguments[0].click();",
            login_button
        )

        print("[Flipkart] Login popup closed.")

    except TimeoutException:
        pass

    except WebDriverException:
        pass

    # ---------------------------------------------------------
    # 3. Wait for product links
    # ---------------------------------------------------------
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "a[href*='/p/']"
                )
            )
        )

    except TimeoutException:

        # Before declaring failure, check whether product links
        # are already present in the page source.
        try:
            page_source = driver.page_source

            if "/p/" not in page_source:
                shot = _save_debug_screenshot(
                    driver,
                    "flipkart_results_failed"
                )

                raise RuntimeError(
                    "Flipkart's results page did not contain any "
                    "product links. "
                    f"Screenshot saved to: {shot}."
                )

            print(
                "[Flipkart] Wait timed out, but product links "
                "were found in the loaded page."
            )

        except WebDriverException as e:
            shot = _save_debug_screenshot(
                driver,
                "flipkart_results_failed"
            )

            raise RuntimeError(
                "Flipkart results could not be read. "
                f"Screenshot saved to: {shot}. Error: {e}"
            )

    # ---------------------------------------------------------
    # 4. Parse page
    # ---------------------------------------------------------
    soup = BeautifulSoup(
        driver.page_source,
        "html.parser"
    )

    raw_products = []
    seen_links = set()

    # ---------------------------------------------------------
    # 5. Find product links
    # ---------------------------------------------------------
    for link in soup.find_all("a", href=True):

        href = link["href"]

        if "/p/" not in href:
            continue

        full_link = (
            href
            if href.startswith("http")
            else "https://www.flipkart.com" + href
        )

        if full_link in seen_links:
            continue

        # -----------------------------------------------------
        # Extract title
        # -----------------------------------------------------
        img = link.find("img", alt=True)

        title = None

        if img and img.get("alt"):
            img_alt = img.get("alt").strip()

            if len(img_alt) > 5:
                title = img_alt

        if not title and link.get("title"):
            title = link.get("title").strip()

        if not title:
            text = link.get_text(
                " ",
                strip=True
            )

            title = text[:100]

        if not title or len(title) < 5:
            continue

        title = re.sub(
            r"\s+",
            " ",
            title
        )

        title = title[
            :MAX_TITLE_LENGTH
        ].strip()

        # -----------------------------------------------------
        # Extract price
        # -----------------------------------------------------
        price = None

        container = link

        for _ in range(6):

            container = container.parent

            if container is None:
                break

            container_text = container.get_text(
                " ",
                strip=True
            )

            match = PRICE_PATTERN.search(
                container_text
            )

            if match:
                price = match.group()
                break

        seen_links.add(full_link)

        raw_products.append(
            {
                "title": title,
                "price": price,
                "rating": "Not Available",
                "reviews": "Not Available",
                "link": full_link,
                "source": "Flipkart",
            }
        )

    # ---------------------------------------------------------
    # 6. Debug information
    # ---------------------------------------------------------
    print(
        f"[Flipkart] product links found: "
        f"{len(raw_products)}"
    )

    for p in raw_products[:5]:
        print(
            f"  - {p['title']} | {p['price']}"
        )

    return raw_products


def search_flipkart_product(
    product_name,
    driver,
    top_n=5
):
    """
    Search Flipkart and return only genuine matches.
    """

    product_name = (
        product_name or ""
    ).strip()

    if not product_name:
        return []

    try:

        raw_products = scrape_flipkart_raw(
            product_name,
            driver
        )

        matched = match_products(
            product_name,
            raw_products
        )[:top_n]

        print(
            f"[Flipkart] passed strict match filter: "
            f"{len(matched)} / {len(raw_products)}"
        )

        return matched

    except Exception as e:

        print(
            f"[Flipkart] scraping failed: {e}"
        )

        return []