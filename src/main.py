# -*- coding: utf-8 -*-

import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import json
import html as htmlesc

import argparse, time, sys, traceback, json

import requests
from bs4 import BeautifulSoup
from bs4 import NavigableString
from urllib.parse import urljoin
from urllib.parse import quote, urljoin
from urllib.parse import urlsplit, urlunsplit
from playwright.sync_api import sync_playwright

# ----------------------------------
# ÜLDINE KONF / ABI
# ----------------------------------

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

FETCH_RATINGS_MAX_PER_STORE = 1   
FETCH_RATINGS_TIMEOUT_S = 25

STORE_DEFAULT_QUERIES = {
    "1a": "Mängukontroller Sony DualSense, valge/must",
    "kaup24": "Sony DualSense valge",
}

def _best_rating_from_html(html: str) -> str:
    for f in (_jsonld_rating_from_html, _parse_rating_from_html):
        try:
            v = f(html)
            if v:
                return f"{float(str(v).replace(',', '.')):.1f}"
        except Exception:
            pass

    lower = html.lower()

    m = re.search(r'itemprop=["\']ratingvalue["\'][^>]*content=["\']([0-5](?:[.,]\d)?)', lower)
    if not m:
        m = re.search(r'"ratingvalue"\s*:\s*"?([0-5](?:[.,]\d)?)"?', lower)
    if not m:
        m = re.search(r'aria-label=["\'][^"\']*([0-5](?:[.,]\d)?)\s*/\s*5', lower)
    if not m:
        m = re.search(r'data-rating(?:-value)?=["\']([0-5](?:[.,]\d)?)', lower)

    if m:
        try:
            return f"{float(m.group(1).replace(",", ".")):.1f}"
        except Exception:
            return m.group(1).replace(",", ".")
    return ""

def _price_from_1a_pdp(base: str, href: str) -> str:
    try:
        url = urljoin(base, href)
        r = requests.get(url, headers=HDRS, timeout=20)
        if r.status_code != 200:
            return ""
        s = BeautifulSoup(r.text, "lxml")
        meta = s.select_one('meta[itemprop="price"][content]')
        if meta and meta.get("content"):
            return clean_price(meta["content"])
        txt = s.get_text(" ", strip=True)
        m = re.search(r"(\d+[\s.,]\d{2})\s*€", txt)
        return clean_price(m.group(1)) if m else ""
    except Exception:
        return ""

import json

def _parse_rating_from_html(html: str) -> str:
    """Proovi võtta reiting JSON-LD-st või tähisest .c-rating."""
    soup = BeautifulSoup(html, "lxml")

    for s in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(s.string or "{}")
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if isinstance(obj, dict) and obj.get("aggregateRating"):
                val = obj["aggregateRating"].get("ratingValue")
                if val:
                    return str(val).strip()
    el = (soup.select_one('[itemprop="aggregateRating"] [itemprop="ratingValue"]') or
          soup.select_one(".c-rating [data-rating]") or
          soup.select_one(".c-rating__value"))
    if el:
        return (el.get("content") or el.get("data-rating") or el.get_text(strip=True) or "").strip()
    return ""

import json

def _extract_prices_generic(node) -> tuple[str, str]:
    txt = node.get_text(" ", strip=True)
    nums = re.findall(r"(\d+[\s.,]\d{2})\s*€", txt) or re.findall(r"\d+[\s.,]\d{2}", txt)
    if not nums:
        return "", ""

    def to_f(s):
        try:
            return float(s.replace(" ", "").replace(",", "."))
        except:
            return None

    if len(nums) >= 2:
        a, b = to_f(nums[0]), to_f(nums[1])
        if a is not None and b is not None and b < a:
            return f"{a:.2f}", f"{b:.2f}"

    a = to_f(nums[0])
    return (f"{a:.2f}" if a is not None else clean_price(nums[0])), ""

def _jsonld_rating_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for sc in soup.select('script[type="application/ld+json"]'):
        raw = sc.string or sc.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue

        def iter_objs(x):
            if isinstance(x, list):
                for i in x: yield i
            else:
                yield x

        for obj in iter_objs(data):
            if not isinstance(obj, dict):
                continue
            if obj.get("@type") == "Product":
                ar = obj.get("aggregateRating") or {}
                val = ar.get("ratingValue") or ar.get("rating")
                if val is None and isinstance(ar, dict):
                    val = ar.get("ratingValue")
                if val is not None:
                    try:
                        f = float(str(val).replace(",", "."))
                        return f"{f:.1f}"
                    except Exception:
                        pass
            if obj.get("@type") == "AggregateRating":
                val = obj.get("ratingValue")
                if val is not None:
                    try:
                        f = float(str(val).replace(",", "."))
                        return f"{f:.1f}"
                    except Exception:
                        pass
    return ""

def _kaup24_widget_json(card):
    wd = card.get("widget-data") or card.get("widgetdata") or ""
    if not wd:
        return None
    try:
        return json.loads(htmlesc.unescape(wd))
    except Exception:
        return None

from zoneinfo import ZoneInfo
import re

def _parse_price(text: str):
    if not text:
        return None
    t = text.replace("\xa0", " ").replace("€", "").strip()
    t = t.replace(",", ".")
    m = re.search(r"(\d+)(?:\.(\d{2}))?", t)
    if m:
        whole = m.group(1)
        frac = m.group(2) or "00"
        try:
            return float(f"{whole}.{frac}")
        except:
            return None
    return None

HDRS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.euronics.ee/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def read_query(path="configs/default.txt") -> str:
    return Path(path).read_text(encoding="utf-8").strip()

def now_tallinn():
    tz = ZoneInfo("Europe/Tallinn")
    now = datetime.now(tz)
    human = now.strftime("%d.%m.%Y %H:%M")
    iso = now.isoformat()
    return human, iso

def _fmt_money(val) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return f"{val:.2f}"
    s = str(val).replace("€", "").replace("\xa0", "").strip()
    s = s.replace(",", ".")
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return ""

def _fmt_text(val) -> str:
    return "" if val is None else str(val).strip()

def _fmt_rating(val) -> str:
    """Tagasta reiting kujul 'X/5' või 'Puudub'."""
    if val is None:
        return "Puudub"
    s = str(val).strip()
    if not s:
        return "Puudub"
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return "Puudub"
    n = int(round(max(0.0, min(5.0, f))))
    return f"{n}/5"

def row_to_tr(row: dict) -> str:
    name = _fmt_text(row.get("name") or "—")
    url = _fmt_text(row.get("url") or "#")
    price = _fmt_money(row.get("price"))
    sale_raw = _fmt_money(row.get("sale_price"))
    rating = _fmt_rating(row.get("rating"))
    store = _fmt_text(row.get("store") or row.get("shop"))

    sale = sale_raw if sale_raw else "Puudub"

    name_html = (
        f'<a href="{url}" target="_blank" rel="noopener">{name or "—"}</a>'
        if url and url != "#"
        else (name or "—")
    )
    link_html = (
        f'<a href="{url}" target="_blank" rel="noopener">Ava</a>'
        if url and url != "#"
        else ""
    )

    return (
        "<tr>"
        f"<td>{name_html}</td>"
        f"<td>{price}</td>"
        f"<td>{sale}</td>"
        f"<td>{rating}</td>"
        f"<td>{store}</td>"
        f"<td>{link_html}</td>"
        "</tr>"
    )


def render_html(rows, template_path="templates/table.html", out_path="out/tulemused.html", query=""):
    human, iso = now_tallinn()
    tpl = Path(template_path).read_text(encoding="utf-8")
    body = "\n".join(row_to_tr(r) for r in rows)
    html = (
        tpl.replace("<!-- QUERY_NAME -->", query)
           .replace("<!-- GENERATED_AT_HUMAN -->", human)
           .replace("<!-- GENERATED_AT_ISO -->", iso)
           .replace("<!-- ROWS_GO_HERE -->", body)
    )
    Path(out_path).write_text(html, encoding="utf-8")

# ----------------------------------
# KOGUJAD
# ----------------------------------

def text_or_none(el):
    return el.get_text(" ", strip=True) if el else ""

def clean_price(txt: str) -> str:
    if not txt:
        return ""
    t = txt.replace("\xa0", " ").replace("€", "").strip()
    t = t.replace(",", ".")
    m = re.findall(r"[0-9]+(?:\.[0-9]+)?", t)
    return m[0] if m else ""

def _canon_url(u: str) -> str:
    if not u:
        return u
    try:
        p = urlsplit(u)
        return urlunsplit((p.scheme, p.netloc, p.path, "", ""))
    except Exception:
        return u

WHITE_TOKENS = ("white", "valge", "pärlmutter", "pearl", "glacier", "midnight white")

ACCESSORY_TOKENS = (
    "laadimis", "charge", "charging", "twin charge", "dock", "docking", "station", "alus",
    "kaabel", "cable", "juhe", "adapter", "stand", "holder", "cradle",
    "kest", "cover", "case", "silikoon", "silico", "kaitse", "protect",
    "snakebyte", "games world", "doubleshock", "third-party"
)

BLOCK_TOKENS = (
    "twin charge", "charging", "charger", "dock", "station", "alus", "cradle",
    "kaabel", "kest", "kaitse", "cover", "case", "silico", "silikon",
    "doubleshock", "snakebyte", "third party", "kolmanda", "not sony",
    "ps4 ", " playstation 4", "xbox", "switch", "nintendo"
)

def _is_dualsense_white(name: str) -> bool:
    n = (name or "").lower()
    if "dualsense" not in n:
        return False
    if not any(w in n for w in WHITE_TOKENS):
        return False
    if any(tok in n for tok in ACCESSORY_TOKENS):
        return False
    if any(tok in n for tok in BLOCK_TOKENS):
        return False
    return True

import re

_ALPHA = "a-z0-9äöõü"

def _norm(s: str) -> str:
    return re.sub(rf"[^{_ALPHA}]+", " ", (s or "").lower()).strip()

def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word.lower())}\b", _norm(text)) is not None

def _has_any(text: str, words: tuple[str, ...]) -> bool:
    t = _norm(text)
    return any(re.search(rf"\b{re.escape(w)}\b", t) for w in words)

def filter_rows(rows, query, debug=False):
    q = (query or "").lower()
    force_white = any(t in q for t in ("white", "valge", "pärlmutter", "pearl", "glacier"))

    kept = []
    for r in rows:
        name = r.get("name") or ""
        url  = r.get("url")  or ""
        store = (r.get("store") or r.get("shop") or "").strip()

        name_n = _norm(name)
        url_n  = _norm(url)

        is_dualsense = ("dualsense" in name_n) or ("dualsense" in url_n)
        if not is_dualsense:
            if debug: print(f"[FILTER skip] not DualSense :: {store} :: {name}")
            continue

        if force_white and not (_has_any(name, WHITE_TOKENS) or _has_any(url, WHITE_TOKENS)):
            if debug: print(f"[FILTER skip] no WHITE :: {store} :: {name}")
            continue

        if _has_any(name, BLOCK_TOKENS) or _has_any(url, BLOCK_TOKENS):
            if debug: print(f"[FILTER skip] BLOCK token :: {store} :: {name}")
            continue

        kept.append(r)

    return kept

def _canon_url(u: str) -> str:
    if not u:
        return u
    try:
        p = urlsplit(u)
        return urlunsplit((p.scheme, p.netloc, p.path, "", ""))
    except Exception:
        return u

def extract_euronics_price(card) -> str:
    pbox = card.select_one("div.price")
    if not pbox:
        return ""

    whole = None
    for node in pbox.children:
        if isinstance(node, NavigableString):
            s = (str(node) or "").strip()
            if s.isdigit():
                whole = s
                break

    frac = None
    cp = pbox.select_one("span.cp")
    if cp:
        m = re.search(r"(\d{2})", cp.get_text(" ", strip=True))
        if m:
            frac = m.group(1)

    if whole and frac:
        return f"{whole}.{frac}"

    meta = card.select_one('[itemprop="price"][content]')
    if meta and meta.get("content"):
        return clean_price(meta["content"])

    return clean_price(pbox.get_text(" ", strip=True))

def collect_euronics(query: str) -> list[dict]:
    import re, requests
    from bs4 import BeautifulSoup, NavigableString
    from urllib.parse import urljoin, quote
    from pathlib import Path

    base = "https://www.euronics.ee"
    search_url = f"{base}/otsing/{quote(query, safe='')}"
    category_url = f"{base}/meelelahutus/puldid-ja-roolid/puldid"

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": base + "/",
        "Connection": "keep-alive",
    }

    def clean_price(txt: str) -> str:
        if not txt:
            return ""
        t = txt.replace("\xa0", " ").replace("€", "").strip()
        t = t.replace(",", ".")
        m = re.findall(r"[0-9]+(?:\.[0-9]+)?", t)
        return m[0] if m else ""

    def parse_cards(html: str, label: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        Path("out/debug_euronics.html").write_text(html, encoding="utf-8", errors="ignore")

        cards = soup.select("article.product-card, div.product-card")
        print(f"Euronics({label}): kaarte DOM-is = {len(cards)}")
        rows = []

        for i, card in enumerate(cards, 1):
            a = (
                card.select_one("a.product-card__title[href]") or
                card.select_one("h3 a[href]") or
                max(
                    (x for x in card.select("a[href]") if (x.get_text(strip=True) or x.get("title"))),
                    key=lambda x: len((x.get("title") or x.get_text(strip=True) or "")),
                    default=None
                )
            )
            name = (a.get("title") or a.get_text(" ", strip=True) or "").strip() if a else ""
            href = a.get("href", "") if a else ""
            link = urljoin(base, href) if href else ""
            if not name:
                img = card.select_one("img[alt]")
                if img and img.get("alt"):
                    name = img["alt"].strip()

            pbox = card.select_one("div.price")
            if pbox:
              whole_node = next((t for t in pbox.children if isinstance(t, NavigableString)), "")
              whole = (whole_node or "").strip()
              frac = pbox.select_one("span.cp")
              frac_txt = frac.get_text("", strip=True) if frac else ""
              price_txt = f"{whole}{frac_txt}"
            else:
              price_txt = card.get_text(" ", strip=True)

            price = extract_euronics_price(card)

            sale_price = ""
            old_el = card.select_one(".price--old, .old-price")
            if old_el:
                old = clean_price(old_el.get_text(" ", strip=True))
                try:
                    if old and price and float(old) > float(price):
                        sale_price = price
                        price = old
                except:
                    pass

            if link and price:
                if not _is_dualsense_white(name):
                    continue
                rows.append({
                    "name": name or "—",
                    "price": price,
                    "sale_price": sale_price,
                    "rating": "",
                    "store": "Euronics",
                    "url": link,
                })

            if i <= 3:
                Path(f"out/euro_card_{label}_{i}.html").write_text(card.prettify(), encoding="utf-8")

        return rows

    r = requests.get(search_url, headers=headers, timeout=20)
    print(f"Euronics status: {r.status_code} (search)")
    if r.status_code == 200:
        rows = parse_cards(r.text, "search")
        if rows:
            print(f"Euronics: leidsin {len(rows)} rida (otsinguleht)")
            return rows
        else:
            print("[WARN] kirjutasin out/debug_euronics.html (0 rida)")

    r2 = requests.get(category_url, headers=headers, timeout=20)
    print(f"Euronics status: {r2.status_code} (category)")
    if r2.status_code == 200:
        rows = parse_cards(r2.text, "category")
        print(f"Euronics: leidsin {len(rows)} rida (kategooria)")
        return rows

    return []

    rows = extract_from_cards(soup)
    if rows:
        print(f"Euronics: leidsin {len(rows)} rida (otsinguleht)")
        return rows

    price_boxes = soup.select("div.price")
    print(f"Euronics(fallback): hinnakaste DOM-is = {len(price_boxes)}")
    parents, seen = [], set()
    for box in price_boxes:
        par = box
        for _ in range(8):
            par = par.parent
            if not par:
                break
            if par.name in ("article", "div", "li"):
                if id(par) not in seen:
                    seen.add(id(par))
                    parents.append(par)
                break

    for i, card in enumerate(parents[:3], 1):
        Path(f"out/euro_fallback_{i}.html").write_text(card.prettify(), encoding="utf-8")

    rows = []
    for card in parents:
        a = max(
            (x for x in card.select("a[href]") if (x.get_text(strip=True) or x.get("title"))),
            key=lambda x: len((x.get("title") or x.get_text(strip=True) or "")),
            default=None
        )
        if not a:
            continue
        name = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        href = a.get("href", "")
        link = urljoin(base, href) if href else ""
        if not name:
            img = card.select_one("img[alt]")
            if img and img.get("alt"):
                name = img["alt"].strip()

        pbox = card.select_one("div.price")
        if pbox:
            whole = (pbox.find(text=True, recursive=False) or "").strip()
            frac = pbox.select_one("span.cp")
            price_txt = f"{whole}{(frac.get_text('', strip=True) if frac else '')}"
        else:
            price_txt = card.get_text(" ", strip=True)
        price = clean_price(price_txt)

        if link and price:
            rows.append({
                "name": name or "—",
                "price": price,
                "sale_price": "",
                "rating": "",
                "store": "Euronics",
                "url": link,
            })

    print(f"Euronics: leidsin {len(rows)} rida (fallback)")
    return rows

    rows = extract_from_cards(soup)
    if rows:
        print(f"Euronics: leidsin {len(rows)} rida (otsinguleht)")
        return rows

    price_boxes = soup.select("div.price")
    print(f"Euronics(fallback): hinnakaste DOM-is = {len(price_boxes)}")
    parents, seen = [], set()
    for box in price_boxes:
        par = box
        for _ in range(8):
            par = par.parent
            if not par:
                break
            if par.name in ("article", "div", "li"):
                if id(par) not in seen:
                    seen.add(id(par))
                    parents.append(par)
                break

    for i, card in enumerate(parents[:3], 1):
        Path(f"out/euro_fallback_{i}.html").write_text(card.prettify(), encoding="utf-8")

    rows = []
    for card in parents:
        a = max(
            (x for x in card.select("a[href]") if (x.get_text(strip=True) or x.get("title"))),
            key=lambda x: len((x.get("title") or x.get_text(strip=True) or "")),
            default=None
        )
        if not a:
            continue
        name = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        href = a.get("href", "")
        link = urljoin(base, href) if href else ""
        if not name:
            img = card.select_one("img[alt]")
            if img and img.get("alt"):
                name = img["alt"].strip()

        pbox = card.select_one("div.price")
        if pbox:
            whole = (pbox.find(text=True, recursive=False) or "").strip()
            frac = pbox.select_one("span.cp")
            price_txt = f"{whole}{(frac.get_text('', strip=True) if frac else '')}"
        else:
            price_txt = card.get_text(" ", strip=True)
        price = clean_price(price_txt)

        if link and price:
            rows.append({
                "name": name or "—",
                "price": price,
                "sale_price": "",
                "rating": "",
                "store": "Euronics",
                "url": link,
            })

    print(f"Euronics: leidsin {len(rows)} rida (fallback)")
    return rows

def collect_klick(query: str) -> list[dict]:

    API_BASE = "https://eucs18.ksearchnet.com/cloud-search/n-search/search"
    API_KEY = "klevu-15841061761132273"

    params = {
        "ticket": API_KEY,
        "term": query,
        "paginationStartsFrom": "0",
        "sortPrice": "false",
        "ipAddress": "undefined",
        "analyticsApiKey": API_KEY,
        "showOutOfStockProducts": "true",
        "klevuFetchPopularTerms": "true",
        "klevu_priceInterval": "500",
        "fetchMinMaxPrice": "true",
        "klevu_multiSelectFilters": "true",
        "noOfResults": "40",
        "klevuSort": "rel",
        "enableFilters": "true",
        "filterResults": "",
        "visibility": "search",
        "category": "KLEVU_PRODUCT",
        "responseType": "json",
    }
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Referer": "https://www.klick.ee/",
    }

    try:
        r = requests.get(API_BASE, params=params, headers=headers, timeout=20)
        print(f"Klick status: {r.status_code}")
        if r.status_code != 200:
            return []
        data = r.json()

        records = []
        res = data.get("result")
        if isinstance(res, list) and res:
            first = res[0]
            if isinstance(first, dict) and "records" in first:
                records = first.get("records", [])
            else:
                records = res

        rows = []
        def to_float(s):
            try:
                return float(str(s).replace(",", "."))
            except:
                return None

        for rec in records:
            name = (rec.get("name") or "").strip()
            url = (rec.get("url") or "").strip()
            sale_price = (rec.get("salePrice") or rec.get("price") or rec.get("basePrice") or "")
            old_price = (rec.get("oldPrice") or "")

            sp = to_float(sale_price)
            op = to_float(old_price)

            if op and sp and op > sp:
                price = f"{op:.2f}"       
                discount = f"{sp:.2f}"     
            else:
                price = f"{(sp or 0):.2f}" if sp is not None else ""
                discount = ""

            if not (name and url and price):
                continue

            rows.append({
                "name": name,
                "price": price,
                "sale_price": discount,
                "rating": "",
                "store": "Klick",
                "url": url,
            })

        print(f"Klick: leidsin {len(rows)} rida (API)")
        return rows

    except Exception as e:
        print(f"[Klick ERROR] {e}")
        return []

def collect_1a_pw(query: str) -> list[dict]:
    rows: list[dict] = []
    q = (STORE_DEFAULT_QUERIES.get("1a") if 'STORE_DEFAULT_QUERIES' in globals() else None) or query
    search_url = f"https://www.1a.ee/otsing?q={quote(q, safe='')}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            locale="et-EE",
            extra_http_headers={"Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7"},
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.goto(search_url, wait_until="networkidle", timeout=45000)
        try:
            page.wait_for_selector(".lupa-search-result-product-card, [data-cy='lupa-search-result-product-card']",
                                   timeout=10000)
        except Exception:
            pass
        html = page.content()
        context.close(); browser.close()

    Path("out/debug_1a_pw.html").write_text(html, encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.lupa-search-result-product-card, [data-cy='lupa-search-result-product-card']")
    print(f"1a(PW): leidsin {len(cards)} kaarti")

    def looks_like_controller(name: str) -> bool:
        n = (name or "").lower()
        if any(x in n for x in ("laadimis", "dock", "charging", "charger", "station", "alus", "kaabel", "kaabl", "katte",
                                 "kaitse", "kest", "silico", "siliko", "cradle", "alus", "holder")):
            return False
        return ("dualsense" in n) or ("kontroller" in n) or ("controller" in n)

    def _extract_1a_name_link_prices(card) -> tuple[str, str, str, str]:
        a = card.select_one("a[href]")
        href = a.get("href", "") if a else ""
        if href.startswith("/"):
            href = "https://www.1a.ee" + href

        name = (a.get_text(strip=True) if a else "") or ""
        if not name:
            img = card.select_one("img[alt]")
            if img:
                name = (img.get("alt") or "").strip()

        sale_txt = ""
        price_txt = ""

        sale_el = (card.select_one("span.catalog-taxons-product-price__price-number") or
                   card.select_one("[class*='price-number']") or
                   card.select_one("[class*='price-current']"))
        if sale_el:
            sale_txt = sale_el.get_text(" ", strip=True)

        old_el = (card.select_one("span.catalog-taxons-product-price__item-price") or
                  card.select_one("[class*='old']") or
                  card.select_one("del"))
        if old_el:
            price_txt = old_el.get_text(" ", strip=True)

        sale = clean_price(sale_txt)
        price = clean_price(price_txt)

        if not sale or not price:
            txt = card.get_text(" ", strip=True)
            nums = re.findall(r"(\d+[\s.,]\d{2})\s*€", txt) or re.findall(r"(\d+[\s.,]\d{2})", txt)

            def tf(s: str):
                try:
                    return float(s.replace(" ", "").replace(",", "."))
                except Exception:
                    return None

            vals = [tf(n) for n in nums if tf(n) is not None]
            vals = sorted(set(vals))
            if vals:
                lo, hi = vals[0], vals[-1]
                if len(vals) > 1 and hi > lo + 0.01:
                    if not price:
                        price = f"{hi:.2f}"
                    if not sale:
                        sale = f"{lo:.2f}"
                else:
                    if not price and not sale:
                        price = f"{lo:.2f}"

        return name, href, price, sale

    fails = 0
    new_rows: list[dict] = []
    for card in cards:
        name, href, price, sale = _extract_1a_name_link_prices(card)

        if not looks_like_controller(name):
            continue

        if not (name and href and (price or sale)):
            if fails < 5:
                Path(f"out/1a_fail_{fails+1}.html").write_text(card.prettify(), encoding="utf-8")
            fails += 1
            continue

        price_final = price or ""
        sale_final  = sale or ""
        if not price_final and sale_final:
            price_final = sale_final  

        new_rows.append({
            "name": name,
            "price": price_final,
            "sale_price": sale_final,
            "rating": "",
            "store": "1a",
            "url": _canon_url(href),
        })

    seen_urls = set()
    rows = []
    for r in new_rows:
        key = r["url"]
        if key in seen_urls:
            continue
        seen_urls.add(key)
        rows.append(r)

    max_per = min(globals().get("FETCH_RATINGS_MAX_PER_STORE", 0) or 0, len(rows))
    if max_per:
        with sync_playwright() as pw2:
            b2 = pw2.chromium.launch(headless=True)
            c2 = b2.new_context(user_agent=UA, locale="et-EE",
                                extra_http_headers={"Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7"})
            p2 = c2.new_page()
            done = 0
            for r in rows:
                if r.get("rating"):
                    continue
                try:
                    p2.goto(r["url"], wait_until="networkidle",
                            timeout=(globals().get("FETCH_RATINGS_TIMEOUT_S", 25)) * 1000)
                    p2.wait_for_timeout(1200)
                    html_detail = p2.content()
                    rating = _best_rating_from_html(html_detail)
                    if rating:
                        r["rating"] = rating
                except Exception as e:
                    print(f"[1a rating WARN] {e}")
                done += 1
                if done >= max_per:
                    break
            c2.close(); b2.close()

    print(f"1a(PW): leidsin {len(rows)} rida")
    if not rows:
        print("[WARN] 1a(PW): 0 rida – vaata out/debug_1a_pw.html ja out/1a_fail_*.html")
    return rows

def collect_kaup24_pw(query: str) -> list[dict]:
    rows = []
    q = (STORE_DEFAULT_QUERIES.get("Kaup24") if 'STORE_DEFAULT_QUERIES' in globals() else None) or query
    search_url = f"https://www.kaup24.ee/et/sq?q={quote(q, safe='')}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            locale="et-EE",
            extra_http_headers={"Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7"},
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.goto(search_url, wait_until="networkidle", timeout=45000)
        try:
            page.wait_for_selector("div.c-product-card, div.catalog-taxons-product-grid__item", timeout=10000)
        except:
            pass
        html = page.content()
        context.close(); browser.close()

    Path("out/debug_kaup24_pw.html").write_text(html, encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.c-product-card, div.catalog-taxons-product-grid__item")
    print(f"Kaup24(PW): leidsin {len(cards)} kaarti")

    def extract_name_and_link(card):
        a = (card.select_one("a.c-product-card__name[href]") or
             card.select_one("a[href*='/mangukonsoolid']") or
             card.select_one("a[href^='/et/']") or
             card.select_one("a[href]"))
        if not a:
            return "", ""
        name = a.get_text(strip=True)
        href = a.get("href", "")
        if href and not href.startswith("http"):
            href = "https://www.kaup24.ee" + href
        return name, href

    def extract_prices(card) -> tuple[str, str]:
        meta = card.select_one('[itemprop="price"][content]')
        if meta and meta.get("content"):
            return clean_price(meta["content"]), ""

        pbox = (card.select_one("div.c-price") or
                card.select_one("span.c-price") or
                card.select_one("span.h-price--medium") or
                card.select_one("span.price") or
                card)
        txt = pbox.get_text(" ", strip=True) if pbox else ""
        nums = re.findall(r"(\d+[\s.,]\d{2})\s*€", txt) or re.findall(r"\d+[\s.,]\d{2}", txt)
        if not nums:
            return "", ""

        def tf(s):
            try:
                return float(s.replace(" ", "").replace(",", "."))
            except:
                return None

        if len(nums) >= 2:
            a, b = tf(nums[0]), tf(nums[1])
            if a is not None and b is not None and b < a:
                return f"{a:.2f}", f"{b:.2f}"

        a = tf(nums[0])
        return (f"{a:.2f}" if a is not None else clean_price(nums[0])), ""

        fails = 0
    for i, card in enumerate(cards, start=1):

        j = _kaup24_widget_json(card)
        if j:
            meta = j.get("meta") or {}
            name = (j.get("title") or meta.get("title") or "").strip()
            url  = (j.get("url") or "").strip()
            sell = (
                meta.get("sell_price") or meta.get("sellPrice")
                or j.get("sell_price") or j.get("sellPrice")
            )
            price = _fmt_money(sell) if sell is not None else ""

            if not _is_dualsense_white(name):
                continue

            if not _is_dualsense_white(name):
                continue
 
            if name and url and price:
                rows.append({
                    "name": name,
                    "price": price,
                    "sale_price": "",
                    "rating": "",
                    "store": "Kaup24",
                    "url": url,
                })
                continue 

        name, href = extract_name_and_link(card)
        if not _is_dualsense_white(name):
            continue

        price, sale = extract_prices(card)
        if not (name and href and price):
            if fails < 5:
                Path(f"out/kaup24_fail_{fails+1}.html").write_text(card.prettify(), encoding="utf-8")
            fails += 1
            continue

        rows.append({
            "name": name,
            "price": price,
            "sale_price": sale,
            "rating": "",
            "store": "Kaup24",
            "url": href,
        })

    print(f"Kaup24(PW): leidsin {len(rows)} rida")
    if not rows:
        print("[WARN] Kaup24(PW): 0 rida – vaata out/debug_kaup24_pw.html ja out/kaup24_fail_*.html")

    max_per = (globals().get("FETCH_RATINGS_MAX_PER_STORE", 0) or 0)
    if max_per and rows:
        with sync_playwright() as pw2:
            browser2 = pw2.chromium.launch(headless=True)
            context2 = browser2.new_context(
                user_agent=UA, locale="et-EE",
                viewport={"width": 1366, "height": 900}
            )
            page2 = context2.new_page()
            for r in rows[:max_per]:
                try:
                    page2.goto(r["url"], wait_until="domcontentloaded",
                               timeout=(globals().get("FETCH_RATINGS_TIMEOUT_S", 25)) * 1000)
                    rating = _parse_rating_from_html(page2.content())
                    if rating:
                        r["rating"] = rating
                except Exception as e:
                    print(f"[Kaup24 rating WARN] {e}")
            context2.close(); browser2.close()

    return rows

def collect_kaup24(query: str) -> list[dict]:
    return []

def collect_1a(query: str) -> list[dict]:
    return []

# ----------------------------------
# KOONDAJA + MAIN
# ----------------------------------

import re

def _normalize_for_match(s: str) -> str:
    """Normaliseeri: väiketähed, sünonüümid, ainult [a-z0-9 ] ja tühikute kokkutõmme."""
    s = (s or "").lower()

    s = s.replace("playstation5", "playstation 5")
    s = s.replace("ps 5", "ps5")
    s = s.replace("ps5", "ps5")
    s = s.replace("playstation 5", "ps5")
    s = s.replace("dual sense", "dualsense")
    s = s.replace("dual-sense", "dualsense")

    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

WHITE_TOKENS = ("white", "valge", "pärlmutter", "pearl")

NONWHITE_TOKENS_STRICT = (
    "roheline", "green",
    "sinine", "blue",
    "punane", "red",
    "hõbe", "hõbed", "silver",
    "hall", "grey", "gray",
    "camouflage", "kamuflaaž", "kamo",
    "roosa", "pink",
    "kuld", "gold",
    "lilla", "purple"
)

def _is_dualsense_white(name: str) -> bool:
    n = (name or "").lower()
    if not any(t in n for t in ("dualsense", "ps5", "playstation 5")):
        return False
    if not any(w in n for w in WHITE_TOKENS):
        return False
    if any(c in n for c in NONWHITE_TOKENS_STRICT):
        return False
    return True

def collect_all(query: str) -> list[dict]:
    all_rows = []
    for fn in (collect_klick, collect_euronics, collect_1a_pw, collect_kaup24_pw):
        try:
            all_rows.extend(fn(query))
        except Exception as e:
            print(f"[WARN] {fn.__name__} ebaõnnestus: {e}")
    return all_rows

def parse_interval(s: str | int | float | None) -> int:
    """
    Lubab '900', '15m', '1h', '2.5m', '1d'. Tagastab sekundid (int).
    """
    if s is None:
        return 0
    s = str(s).strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", s)
    if not m:
        return int(float(s))
    val = float(m.group(1))
    unit = m.group(2) or "s"
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return int(val * mult)

def run_once(override_query: str | None = None) -> dict:
    q = override_query or read_query()
    print(f"[RUN] {datetime.now().isoformat()} • query='{q}'")
    rows = collect_all(q)
    before = len(rows)
    rows = filter_rows(rows, q)
    render_html(rows, query=q)

    human, iso = now_tallinn()
    info = {"generated_at": iso, "query": q, "found_raw": before, "after_filter": len(rows)}
    Path("out/last_success.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {before} → {len(rows)} rida • out/tulemused.html")
    return info

def parse_interval(s: str | int | float | None) -> int:
    if s is None:
        return 0
    s = str(s).strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", s)
    if not m:
        return int(float(s))
    val = float(m.group(1))
    unit = m.group(2) or "s"
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return int(val * mult)

def main():
    parser = argparse.ArgumentParser(description="Hinnad – koondkoguja")
    parser.add_argument("--every", help="Käivita perioodiliselt (nt '15m', '900', '1h'). Vaikimisi üks kord.")
    parser.add_argument("--query", help="Kirjuta üle configs/default.txt päringuga.")
    args = parser.parse_args()

    interval = parse_interval(args.every) if args.every else 0

    if not interval:
        run_once(args.query)
        return

    print(f"[DAEMON] Käivitan iga {interval} sekundi järel. Lõpetamiseks Ctrl+C.")
    while True:
        t0 = time.time()
        try:
            run_once(args.query)
        except KeyboardInterrupt:
            print("\n[DAEMON] Katkestatud kasutaja poolt.")
            break
        except Exception:
            print("[ERROR] Jooks ebaõnnestus – detailid all:", file=sys.stderr)
            traceback.print_exc()
        dt = time.time() - t0
        sleep_s = max(0, interval - dt)
        if sleep_s:
            print(f"[DAEMON] Uuesti {int(sleep_s)} s pärast…")
            time.sleep(sleep_s)

if __name__ == "__main__":
    main()