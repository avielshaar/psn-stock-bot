"""Fetching and parsing Amazon.in product pages to detect stock status."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

IN_STOCK = "in_stock"
OUT_OF_STOCK = "out_of_stock"
BLOCKED = "blocked"      # captcha / 503 / 429 - Amazon is rate limiting us
NOT_FOUND = "not_found"  # 404 / dead ASIN
UNKNOWN = "unknown"      # page loaded but layout not understood
ERROR = "error"          # network error

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

CAPTCHA_MARKERS = (
    "enter the characters you see below",
    "type the characters you see in this image",
    "/errors/validatecaptcha",
    "sorry, we just need to make sure you're not a robot",
    "to discuss automated access to amazon data",
)
UNAVAILABLE_RE = re.compile(
    r"currently unavailable|temporarily out of stock|out of stock|"
    r"we don'?t know when or if this item will be back",
    re.I,
)
CART_SELECTOR = (
    "#add-to-cart-button, #buy-now-button, "
    "input[name='submit.add-to-cart'], input[name='submit.buy-now']"
)


@dataclass
class ProductStatus:
    asin: str
    state: str
    title: str = ""
    price: str = ""
    price_value: Optional[float] = None
    seller: str = ""
    availability_text: str = ""
    http_status: int = 0
    reason: str = ""


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def _first_text(soup, selectors) -> str:
    for sel in selectors:
        for el in soup.select(sel):
            t = _text(el)
            if t:
                return t
    return ""


def parse_price(text: str) -> Optional[float]:
    m = re.search(r"([\d,]+(?:\.\d+)?)", text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def label_matches(label: str, title: str) -> bool:
    """True if the denomination in label (e.g. '₹1000') appears in the product title ('Rs.1000 ...')."""
    digits = re.sub(r"\D", "", label or "")
    if not digits or not title:
        return True
    return re.search(rf"(?<![\d,]){digits}(?![\d,])", title.replace(",", "")) is not None


def parse_product_html(asin: str, html: str, http_status: int = 200) -> ProductStatus:
    low = html.lower()
    if http_status in (403, 429, 503) or any(m in low for m in CAPTCHA_MARKERS):
        return ProductStatus(asin, BLOCKED, http_status=http_status,
                             reason="captcha / rate limited")
    if http_status == 404:
        return ProductStatus(asin, NOT_FOUND, http_status=http_status, reason="HTTP 404")
    if http_status >= 400:
        return ProductStatus(asin, ERROR, http_status=http_status, reason=f"HTTP {http_status}")

    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one("#productTitle"))
    if not title:
        t = _text(soup.select_one("title"))
        if "page not found" in t.lower():
            return ProductStatus(asin, NOT_FOUND, http_status=http_status, reason="page not found")

    avail = _first_text(soup, ["#availability", "#outOfStock", "#availability_feature_div"])
    # Price: only from the buy box area. A generic ".a-price" matches carousels of other products.
    price = _first_text(soup, [
        "#corePrice_feature_div .a-offscreen", "#corePriceDisplay_desktop_feature_div .a-offscreen",
        "#apex_desktop .a-offscreen", "#buybox .a-price .a-offscreen", "#price_inside_buybox",
    ])
    seller = _first_text(soup, [
        "#merchant-info", "#sellerProfileTriggerId",
        "#tabular-buybox .tabular-buybox-text[tabular-attribute-name='Sold by']",
    ])
    if UNAVAILABLE_RE.search(avail) or soup.select_one("#outOfStock") is not None:
        price = ""
    common = dict(title=title, price=price, price_value=parse_price(price),
                  seller=seller, availability_text=avail, http_status=http_status)

    has_cart = soup.select_one(CART_SELECTOR) is not None
    unavailable = bool(UNAVAILABLE_RE.search(avail)) or soup.select_one("#outOfStock") is not None

    if has_cart and not unavailable:
        return ProductStatus(asin, IN_STOCK, reason="buy button present", **common)
    if unavailable and not has_cart:
        return ProductStatus(asin, OUT_OF_STOCK, reason="marked unavailable", **common)
    if has_cart and unavailable:
        return ProductStatus(asin, UNKNOWN, reason="conflicting signals", **common)
    if soup.select_one("#buybox-see-all-buying-choices, #all-offers-display"):
        return ProductStatus(asin, OUT_OF_STOCK, reason="only 'see all buying options'", **common)
    if not title:
        return ProductStatus(asin, UNKNOWN, reason="no product title (layout changed?)", **common)
    return ProductStatus(asin, UNKNOWN, reason="no buy button and no availability text", **common)


class AmazonClient:
    """engine: 'curl_cffi' (impersonates Chrome's TLS fingerprint - far less likely to get a captcha)
    or 'requests' (plain). 'auto' = curl_cffi if installed, else requests."""

    def __init__(self, base_url="https://www.amazon.in", timeout=20, proxy="", engine="auto"):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.proxy = proxy
        self._warm = False
        if engine in ("auto", "curl_cffi"):
            try:
                from curl_cffi import requests as cr
                self.engine = "curl_cffi"
                self.session = cr.Session(impersonate="chrome")
            except Exception:
                if engine == "curl_cffi":
                    raise
                self.engine = "requests"
        else:
            self.engine = "requests"
        if self.engine == "requests":
            self.session = requests.Session()
            self.session.headers.update({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
            })

    def product_url(self, asin: str) -> str:
        return f"{self.base_url}/dp/{asin}"

    def _get(self, url: str):
        kw = {"timeout": self.timeout, "allow_redirects": True}
        if self.proxy:
            kw["proxies"] = {"http": self.proxy, "https": self.proxy}
        if self.engine == "requests":
            kw["headers"] = {"User-Agent": random.choice(USER_AGENTS)}
        else:
            kw["headers"] = {"Accept-Language": "en-IN,en;q=0.9"}
        return self.session.get(url, **kw)

    def fetch_html(self, asin: str):
        """Returns (status_code, html). Visits the home page once first to obtain cookies."""
        if not self._warm:
            try:
                self._get(self.base_url + "/")
            except Exception:
                pass
            self._warm = True
        r = self._get(self.product_url(asin))
        return r.status_code, r.text

    def fetch(self, asin: str) -> ProductStatus:
        try:
            code, html = self.fetch_html(asin)
        except Exception as e:
            return ProductStatus(asin, ERROR, reason=f"network: {e.__class__.__name__}")
        st = parse_product_html(asin, html, code)
        if st.state == BLOCKED:
            self._warm = False          # get fresh cookies next time
        return st
