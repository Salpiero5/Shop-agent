"""Search Marktplaats daily and email matching product listings."""

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from zoneinfo import ZoneInfo


MARKTPLAATS = "https://www.marktplaats.nl"
SEARCH_SITES = {
    "Marktplaats": MARKTPLAATS,
    "AutoScout24": "https://www.autoscout24.nl",
}
PRODUCT_SHOPS = {
    "Tennis-Point.nl": "https://www.tennis-point.nl",
    "Padelshop.com": "https://padelshop.com",
}


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as config_file:
        config = json.load(config_file)
    search_urls = config.get("search_urls")
    if not isinstance(search_urls, dict) or not search_urls:
        raise ValueError("Set at least one search URL in search_urls.")
    for source, search_url in search_urls.items():
        site_url = SEARCH_SITES.get(source)
        if not site_url or not isinstance(search_url, str) or not search_url.startswith(
            f"{site_url}/"
        ):
            raise ValueError(f"Set a valid {source} search URL in search_urls.")
    padel_alert = config.get("padel_alert")
    if not isinstance(padel_alert, dict):
        raise ValueError("Set padel_alert in the config file.")
    shop_urls = padel_alert.get("search_urls")
    if not isinstance(shop_urls, dict) or not shop_urls:
        raise ValueError("Set at least one retailer search URL in padel_alert.")
    for shop, search_url in shop_urls.items():
        shop_url = PRODUCT_SHOPS.get(shop)
        if not shop_url or not isinstance(search_url, str) or not search_url.startswith(
            f"{shop_url}/"
        ):
            raise ValueError(f"Set a valid {shop} search URL in padel_alert.")
    if not isinstance(padel_alert.get("max_price"), (int, float)) or padel_alert[
        "max_price"
    ] <= 0:
        raise ValueError("Set a positive padel_alert max_price.")
    if not isinstance(padel_alert.get("years"), list) or not padel_alert["years"]:
        raise ValueError("Set the allowed model years in padel_alert.")
    if not isinstance(config.get("max_price"), (int, float)) or config["max_price"] <= 0:
        raise ValueError("Set max_price to a positive number in the config file.")
    exclude_keywords = config.get("exclude_keywords", [])
    if not isinstance(exclude_keywords, list) or not all(
        isinstance(keyword, str) and keyword.strip() for keyword in exclude_keywords
    ):
        raise ValueError("exclude_keywords must be a list of non-empty strings.")
    if not isinstance(config.get("alert_email"), str) or "@" not in config["alert_email"]:
        raise ValueError("Set alert_email in the config file.")
    return config


def search_listings(source: str, search_url: str, max_results: int) -> list[dict]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(locale="nl-NL")
            page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            return page.evaluate(
                """(params) => {
                    const {maxResults, source} = params;
                    if (source === 'AutoScout24') {
                        const detailUrls = [];
                        const collectUrls = (value) => {
                            if (Array.isArray(value)) {
                                value.forEach(collectUrls);
                            } else if (value && typeof value === 'object') {
                                if (typeof value.url === 'string'
                                    && value.url.includes('/aanbod/')) {
                                    detailUrls.push(value.url);
                                }
                                Object.values(value).forEach(collectUrls);
                            }
                        };
                        for (const script of document.querySelectorAll(
                            'script[type="application/ld+json"]'
                        )) {
                            try {
                                collectUrls(JSON.parse(script.textContent || 'null'));
                            } catch {}
                        }
                        const cards = Array.from(document.querySelectorAll(
                            '[data-testid="list-item"]'
                        ));
                        return cards.slice(0, maxResults).map((card, index) => {
                            const guid = card.dataset.guid || '';
                            const detailUrl = detailUrls.find((url) =>
                                url.toLowerCase().includes(guid.toLowerCase())
                            );
                            if (!guid || !detailUrl) return null;
                            const registration = card.dataset.firstRegistration || '';
                            const year = registration.split('-').pop();
                            return {
                                id: guid || String(index),
                                source: 'AutoScout24',
                                title: card.querySelector('h2')?.innerText.trim()
                                    || card.innerText.split('\\n')[0],
                                text: (card.innerText || '').trim().slice(0, 1800),
                                url: new URL(detailUrl, location.origin).href,
                                price: card.dataset.price || null,
                                year: year && /^\\d{4}$/.test(year) ? Number(year) : null,
                                mileage: Number(card.dataset.mileage) || null,
                                fuel: card.dataset.fuelType || null
                            };
                        }).filter(Boolean);
                    }
                    const seen = new Set();
                    const listings = [];
                    for (const link of document.querySelectorAll('a[href*="/v/"]')) {
                        const url = new URL(link.href, location.origin);
                        if (url.origin !== location.origin || seen.has(url.pathname)) continue;
                        seen.add(url.pathname);
                        const card = link.closest('li') || link;
                        const image = card.querySelector('img');
                        const text = (card.innerText || '').trim();
                        if (!text) continue;
                        listings.push({
                            id: String(listings.length),
                            source: 'Marktplaats',
                            title: image?.title || image?.alt || text.split('\\n')[0],
                            text: text.slice(0, 1800),
                            url: url.href
                        });
                        if (listings.length >= maxResults) break;
                    }
                    return listings;
                }""",
                {"maxResults": max_results, "source": source},
            )
        finally:
            browser.close()


def search_shop_products(shop: str, search_url: str, max_results: int) -> list[dict]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(locale="nl-NL")
            page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            return page.evaluate(
                """({maxResults, shop}) => {
                    const shopify = window.ShopifyAnalytics?.meta;
                    const products = shopify?.products || [];
                    const currency = shopify?.currency || 'EUR';
                    const offers = [];
                    for (const product of products) {
                        for (const variant of product.variants || []) {
                            const cents = Number(variant.price);
                            if (!Number.isFinite(cents)) continue;
                            const title = variant.name || product.title || product.handle;
                            const price = (cents / 100).toFixed(2);
                            offers.push({
                                id: String(variant.id || product.id),
                                source: shop,
                                title,
                                text: `${product.vendor || ''} ${product.type || ''} ${title}`.trim(),
                                url: new URL(`/products/${product.handle}`, location.origin).href,
                                price,
                                currency
                            });
                            if (offers.length >= maxResults) return offers;
                        }
                    }
                    return offers;
                }""",
                {"maxResults": max_results, "shop": shop},
            )
        finally:
            browser.close()


def parse_price(text: str) -> Decimal | None:
    matches = re.findall(r"€\s*([0-9][0-9. ]*(?:,[0-9]{1,2})?)", text)
    if not matches:
        return None
    normalized = matches[0].replace(".", "").replace(" ", "").replace(",", ".")
    try:
        price = Decimal(normalized)
    except InvalidOperation:
        return None
    return price if price.is_finite() and price >= 0 else None


def send_email(
    listings: list[dict], config: dict, heading: str, subject: str
) -> None:
    sender = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = config["alert_email"]
    if not sender or not app_password:
        raise RuntimeError(
            "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD as environment secrets."
        )

    lines = [heading, ""]
    for listing in listings:
        lines.extend(
            [
                f"Source: {listing['source']}",
                listing["title"],
                f"Price: €{listing['price']}",
                listing["text"],
                listing["url"],
                "",
            ]
        )

    message = EmailMessage()
    message["Subject"] = f"{subject}: {len(listings)} match(es)"
    message["From"] = sender
    message["To"] = recipient
    message.set_content("\n".join(lines))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(message)


def run(config: dict) -> int:
    listings = []
    for source, search_url in config["search_urls"].items():
        listings.extend(
            search_listings(source, search_url, int(config.get("max_results", 40)))
        )
    max_price = Decimal(str(config["max_price"]))
    min_year = int(config.get("min_year", 0))
    max_mileage = int(config.get("max_mileage", 0))
    exclude_keywords = [
        keyword.casefold() for keyword in config.get("exclude_keywords", [])
    ]
    priced_listings = []
    for listing in listings:
        searchable_text = f"{listing['title']} {listing['text']}".casefold()
        if any(keyword in searchable_text for keyword in exclude_keywords):
            continue
        if listing.get("year") is not None and listing["year"] < min_year:
            continue
        if listing.get("mileage") is not None and max_mileage and listing["mileage"] > max_mileage:
            continue
        price_value = listing.get("price")
        price = Decimal(str(price_value)) if price_value is not None else parse_price(
            listing["text"]
        )
        if price is not None and price <= max_price:
            listing["price"] = str(price)
            priced_listings.append(listing)

    if not priced_listings:
        print(f"No listings matched at or below €{max_price}.")
    else:
        send_email(
            priced_listings,
            config,
            "Matching car listings from " + ", ".join(config["search_urls"]),
            "Car search",
        )
        print(f"Sent {len(priced_listings)} matching car listing(s) by email.")

    run_padel_alert(config)
    return 0


def run_padel_alert(config: dict) -> None:
    alert = config["padel_alert"]
    max_price = Decimal(str(alert["max_price"]))
    allowed_years = {str(year) for year in alert["years"]}
    excluded_terms = [term.casefold() for term in alert.get("exclude_terms", [])]
    matches = []

    for shop, search_url in alert["search_urls"].items():
        products = search_shop_products(
            shop, search_url, int(alert.get("max_results", 30))
        )
        for product in products:
            title = product["title"].casefold()
            if "coello motion" not in title:
                continue
            if not any(year in title for year in allowed_years):
                continue
            if any(re.search(rf"\b{re.escape(term)}\b", title) for term in excluded_terms):
                continue
            price_value = product.get("price")
            price = Decimal(str(price_value)) if price_value is not None else None
            if price is not None and price < max_price:
                product["price"] = str(price)
                matches.append(product)

    if not matches:
        print(f"No Coello Motion {', '.join(sorted(allowed_years))} offers below €{max_price}.")
        return

    send_email(
        matches,
        config,
        "Padel racket deals from " + ", ".join(alert["search_urls"]),
        "Padel racket deal",
    )
    print(f"Sent {len(matches)} matching padel racket deal(s) by email.")


def is_scheduled_run_time(config: dict) -> bool:
    timezone = ZoneInfo(config.get("timezone", "Europe/Amsterdam"))
    now = datetime.now(timezone)
    return now.hour == int(config.get("run_hour", 9))


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Marktplaats and email matching listings.")
    parser.add_argument("--config", default="agent_config.json", help="Path to the agent JSON config")
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="Skip the run unless it is the configured local schedule time",
    )
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.scheduled and not is_scheduled_run_time(config):
            print("Skipping this UTC trigger; it is not 09:00 in the configured timezone.")
            return 0
        return run(config)
    except Exception as error:
        print(f"Daily agent failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())