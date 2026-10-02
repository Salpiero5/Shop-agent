"""Check a product page's current price without an AI service."""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

PRICE_PATTERN = re.compile(
    r"(?:(?P<symbol>€|\$|£)\s*(?P<before>[0-9][0-9., ]*)|"
    r"(?P<after>[0-9][0-9., ]*)\s*(?P<code>EUR|USD|GBP)\b)",
    re.IGNORECASE,
)
CURRENCIES = {"€": "EUR", "$": "USD", "£": "GBP"}


def fetch_product_page(url: str) -> dict:
    """Load a page in Chromium and collect text plus common product metadata."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
            return page.evaluate(
                """() => ({
                    title: document.title,
                    url: location.href,
                    text: (document.body?.innerText || '').slice(0, 16000),
                    metadata: Array.from(document.querySelectorAll(
                        'meta[property^="product:"], meta[property^="og:"], '
                        + 'meta[itemprop], script[type="application/ld+json"]'
                    )).map((element) => ({
                        name: element.getAttribute('property')
                            || element.getAttribute('itemprop')
                            || element.getAttribute('name')
                            || 'json-ld',
                        value: element.content || element.textContent || ''
                    })).slice(0, 80)
                })"""
            )
        finally:
            browser.close()


def parse_amount(value: str) -> Decimal | None:
    normalized = re.sub(r"[^0-9.,]", "", value)
    if not normalized:
        return None

    comma = normalized.rfind(",")
    dot = normalized.rfind(".")
    if comma >= 0 and dot >= 0:
        decimal_separator = "," if comma > dot else "."
        grouping_separator = "." if decimal_separator == "," else ","
        normalized = normalized.replace(grouping_separator, "")
        normalized = normalized.replace(decimal_separator, ".")
    elif comma >= 0 or dot >= 0:
        separator = "," if comma >= 0 else "."
        whole, fraction = normalized.rsplit(separator, 1)
        if len(fraction) in (1, 2):
            normalized = f"{whole.replace(separator, '')}.{fraction}"
        else:
            normalized = normalized.replace(separator, "")

    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def find_prices(text: str) -> list[tuple[Decimal, str]]:
    prices = set()
    for match in PRICE_PATTERN.finditer(text):
        raw_amount = (match.group("before") or match.group("after")).rstrip("., ")
        amount = parse_amount(raw_amount)
        if amount is None:
            continue
        symbol = match.group("symbol")
        currency = CURRENCIES.get(symbol) if symbol else match.group("code").upper()
        prices.add((amount, currency))
    return sorted(prices)


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def product_types(product: dict) -> set[str]:
    types = product.get("@type", [])
    if isinstance(types, str):
        types = [types]
    return {
        str(product_type).lower().rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        for product_type in types
    }


def product_offer(product: dict) -> tuple[Decimal, str | None, str] | None:
    offers = product.get("offers", [])
    if isinstance(offers, dict):
        offers = [offers]

    prices = set()
    for offer in offers if isinstance(offers, list) else []:
        if not isinstance(offer, dict) or "price" not in offer:
            continue
        amount = parse_amount(str(offer["price"]))
        if amount is None:
            continue
        currency = offer.get("priceCurrency") or product.get("priceCurrency")
        availability = str(offer.get("availability", "Unknown")).rsplit("/", 1)[-1]
        prices.add((amount, currency, availability))

    if len(prices) == 1:
        return next(iter(prices))
    return None


def extract_product_price(page_data: dict) -> dict:
    page_title = page_data.get("title", "").strip()
    product_name = page_title or "Unknown"
    products = []

    for item in page_data.get("metadata", []):
        if item.get("name", "").lower() != "json-ld":
            continue
        try:
            structured_data = json.loads(item.get("value", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        products.extend(
            node for node in walk_json(structured_data) if "product" in product_types(node)
        )

    if products:
        matching_product = next(
            (
                product
                for product in products
                if isinstance(product.get("name"), str)
                and product["name"].casefold() in page_title.casefold()
            ),
            products[0],
        )
        product_name = matching_product.get("name") or product_name
        offer = product_offer(matching_product)
        if offer is not None:
            amount, currency, availability = offer
            return {
                "product_name": product_name,
                "price": str(amount),
                "currency": currency,
                "availability": availability,
                "confidence": "high",
                "evidence": f"Structured product offer: {amount} {currency or ''}".strip(),
            }

    metadata = {
        item.get("name", "").lower(): item.get("value", "")
        for item in page_data.get("metadata", [])
    }
    amount_value = next(
        (
            metadata[key]
            for key in ("product:price:amount", "og:price:amount", "price")
            if metadata.get(key)
        ),
        None,
    )
    currency = next(
        (
            metadata[key]
            for key in ("product:price:currency", "og:price:currency", "pricecurrency")
            if metadata.get(key)
        ),
        None,
    )
    amount = parse_amount(str(amount_value)) if amount_value is not None else None
    if amount is not None:
        return {
            "product_name": product_name,
            "price": str(amount),
            "currency": currency,
            "availability": "Unknown",
            "confidence": "medium",
            "evidence": f"Product price metadata: {amount} {currency or ''}".strip(),
        }

    prices = find_prices(page_data.get("text", ""))
    if len(prices) == 1:
        amount, currency = prices[0]
        return {
            "product_name": product_name,
            "price": str(amount),
            "currency": currency,
            "availability": "Unknown",
            "confidence": "medium",
            "evidence": f"Only unambiguous currency price in visible page text: {amount} {currency}",
        }

    return {
        "product_name": product_name,
        "price": None,
        "currency": None,
        "availability": "Unknown",
        "confidence": "low",
        "evidence": "No unambiguous current product price found in structured data or page text.",
    }


def check_price(url: str) -> dict:
    page_data = fetch_product_page(url)
    result = extract_product_price(page_data)
    result["url"] = page_data["url"]
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a shopping product's current price.")
    parser.add_argument("url", help="URL of the product page")
    parser.add_argument("--output", help="Write the result to a JSON file")
    args = parser.parse_args()

    parsed_url = urlparse(args.url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        parser.error("url must be an absolute http:// or https:// URL")

    try:
        result = check_price(args.url)
    except Exception as error:
        print(f"Price check failed: {error}", file=sys.stderr)
        return 1

    output = json.dumps(result, indent=2, ensure_ascii=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(output + "\n")

    print(f"Product: {result['product_name'] or 'Unknown'}")
    if result["price"] is None:
        print("Price: Not found reliably")
    else:
        print(f"Price: {result['price']} {result['currency'] or ''}".rstrip())
    print(f"Availability: {result['availability'] or 'Unknown'}")
    print(f"Confidence: {result['confidence']}")
    print(f"Evidence: {result['evidence'] or 'None'}")
    if args.output:
        print(f"Saved: {args.output}")
    return 0 if result["price"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())