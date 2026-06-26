"""Look up nutrition data from Open Food Facts (https://openfoodfacts.org).

This is the **only** module that talks to the network. It is deliberately kept
separate from ``db.py`` (storage) and ``app.py`` (GUI): the GUI calls these
functions to search / fetch, lets the user review the result, then writes the
chosen values through ``db.py`` as usual. It uses only the standard library
(``urllib``), so the packaged ``.exe`` needs no extra dependencies.

``parse_off_product`` is a pure function (no network) and is unit-tested in
``test_foodsource.py``; the ``fetch_*`` / ``search_*`` helpers are thin HTTP
wrappers around it.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

#: Open Food Facts asks callers to identify themselves with a User-Agent.
USER_AGENT = "MyDb/1.0 (https://github.com/Krabus92/MyDb)"

#: Default network timeout, in seconds.
TIMEOUT = 8.0

_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"

#: Our six per-100 g columns -> Open Food Facts nutriment keys (also per 100 g).
_OFF_NUTRIMENT = {
    "fat": "fat_100g",
    "saturated_fat": "saturated-fat_100g",
    "carbs": "carbohydrates_100g",
    "sugar": "sugars_100g",
    "protein": "proteins_100g",
    "salt": "salt_100g",
}

#: The six nutrients, in the order MyDb stores them.
NUTRIENTS = ("fat", "saturated_fat", "carbs", "sugar", "protein", "salt")


def parse_off_product(product: dict) -> dict:
    """Map one Open Food Facts product to MyDb's fields (pure, no network).

    Returns ``{"code": barcode, "name": display name, "nutrition": {...}}`` where
    ``nutrition`` has the six nutrient keys, each a float per 100 g or ``None``
    when that value is missing from the product. ``salt`` falls back to
    ``sodium_100g * 2.5`` when only sodium is given.
    """
    nutriments = product.get("nutriments") or {}

    def value(key: str) -> float | None:
        raw = nutriments.get(key)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    nutrition: dict[str, float | None] = {
        n: value(_OFF_NUTRIMENT[n]) for n in NUTRIENTS
    }
    if nutrition["salt"] is None:
        sodium = value("sodium_100g")
        if sodium is not None:
            nutrition["salt"] = round(sodium * 2.5, 5)

    name = (
        product.get("product_name")
        or product.get("product_name_en")
        or product.get("generic_name")
        or ""
    ).strip()
    brand = (product.get("brands") or "").split(",")[0].strip()
    if brand and brand.lower() not in name.lower():
        display = f"{name} ({brand})" if name else brand
    else:
        display = name

    return {
        "code": str(product.get("code") or "").strip(),
        "name": display,
        "nutrition": nutrition,
    }


def _get_json(url: str, *, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_by_barcode(barcode: str, *, timeout: float = TIMEOUT) -> dict | None:
    """Return the parsed product for a barcode, or ``None`` if not found.

    Raises on network errors (e.g. no internet) — the caller handles those.
    """
    barcode = barcode.strip()
    if not barcode:
        return None
    url = _PRODUCT_URL.format(barcode=urllib.parse.quote(barcode))
    data = _get_json(url, timeout=timeout)
    if data.get("status") == 1 and data.get("product"):
        return parse_off_product(data["product"])
    return None


def search_by_name(
    text: str, *, limit: int = 20, timeout: float = TIMEOUT
) -> list[dict]:
    """Return parsed products matching a search string (possibly empty).

    Raises on network errors — the caller handles those.
    """
    text = text.strip()
    if not text:
        return []
    query = urllib.parse.urlencode(
        {
            "search_terms": text,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": limit,
            "fields": "code,product_name,product_name_en,generic_name,"
            "brands,nutriments",
        }
    )
    data = _get_json(f"{_SEARCH_URL}?{query}", timeout=timeout)
    return [parse_off_product(p) for p in (data.get("products") or [])]
