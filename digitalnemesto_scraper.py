#!/usr/bin/env python3
"""
Scraper pre digitalnemesto.sk – Spišská Nová Ves a jej organizácie
Zberá všetky dostupné údaje o dokumentoch (zmluvy, faktúry, objednávky).

URL štruktúra portálu (SPA, hash routing):
  /#/zverejnovanie/{city-slug}/{org-id}/{doc-type}/{rok}

Príklady:
  /#/zverejnovanie/spisska-nova-ves/spisskanovaves/faktury-dodavatelske/2025
  /#/zverejnovanie/spisska-nova-ves/spisskanovaves/zmluvy/2025

Pouzitie:
  python digitalnemesto_scraper.py                           # SNV - všetky org, typy, roky
  python digitalnemesto_scraper.py --org mesto               # iba Mesto SNV
  python digitalnemesto_scraper.py --keyword stavba          # filter kľúčovým slovom
  python digitalnemesto_scraper.py --typ zmluvy              # iba zmluvy
  python digitalnemesto_scraper.py --rok 2024                # iba rok 2024
  python digitalnemesto_scraper.py --format json             # JSON výstup
  python digitalnemesto_scraper.py --zoznam-org              # vypíše organizácie SNV
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Nainštalujte playwright: pip install playwright && playwright install chromium", file=sys.stderr)
    sys.exit(1)


BASE_URL = "https://www.digitalnemesto.sk"
CURRENT_YEAR = datetime.now().year

# Typy dokumentov – slug v URL portálu → interný kód
DOC_TYPES: dict[str, str] = {
    "zmluvy": "zmluvy",
    "faktury-dodavatelske": "faktury",
    "faktury-odberatelske": "faktury-odberatelske",
    "objednavky": "objednavky",
}

# Organizácie Spišskej Novej Vsi
# Kľúč = org-id v URL portálu, Hodnota = zobrazovaný názov
# Format URL: /#/zverejnovanie/spisska-nova-ves/{org-id}/{typ}/{rok}
SNV_ORGANIZACIE: dict[str, str] = {
    "spisskanovaves":              "Mesto Spišská Nová Ves",
    "muspiskanovaves":             "Mestský úrad SNV",
    "tsspiskanovaves":             "Technické služby SNV",
    "mksspiskanovaves":            "Mestské kultúrne stredisko SNV",
    "mksspn":                      "Mestské kultúrne centrum SNV",
    "kniznicaspiskanovaves":       "Mestská knižnica SNV",
    "bhspiskanovaves":             "Bytové hospodárstvo SNV",
    "socialnecentrumspn":          "Sociálne centrum SNV",
}

SNV_CITY_SLUG = "spisska-nova-ves"

# Skratky pre --org parameter
ORG_SKRATKY: dict[str, str] = {
    "mesto":    "spisskanovaves",
    "mu":       "muspiskanovaves",
    "ts":       "tsspiskanovaves",
    "mks":      "mksspiskanovaves",
    "mkc":      "mksspn",
    "kniznica": "kniznicaspiskanovaves",
    "bh":       "bhspiskanovaves",
    "socialne": "socialnecentrumspn",
}


@dataclass
class Dokument:
    # Organizácia / zdroj
    organizacia: str = ""          # názov organizácie
    org_id: str = ""               # org-id v URL portálu
    rok: str = ""                  # rok dokumentu

    # Identifikácia
    typ: str = ""                  # zmluvy / faktury / faktury-odberatelske / objednavky
    cislo: str = ""                # číslo dokumentu
    id_dokumentu: str = ""         # interné ID na portáli

    # Predmet
    nazov: str = ""                # predmet / názov
    popis: str = ""                # rozšírený popis

    # Dodávateľ / zhotoviteľ
    dodavatel: str = ""            # názov firmy / osoby
    ico: str = ""                  # IČO
    dic: str = ""                  # DIČ
    adresa_dodavatela: str = ""    # adresa

    # Objednávateľ
    objednavatel: str = ""
    oddelenie: str = ""            # oddelenie / referát

    # Financie
    suma: str = ""                 # celková suma vrátane DPH
    suma_bez_dph: str = ""         # suma bez DPH
    mena: str = ""                 # mena (EUR)

    # Dátumy
    datum: str = ""                # dátum podpisu / vystavenia
    datum_ucinnosti: str = ""      # dátum účinnosti / splatnosti
    datum_zverejnenia: str = ""    # dátum zverejnenia
    datum_platnosti_do: str = ""   # platnosť do

    # Kategorizácia
    kategoria: str = ""
    podkategoria: str = ""
    stav: str = ""

    # Súbory a linky
    url: str = ""
    subory: list[str] = field(default_factory=list)

    # Doplnky
    poznamka: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_url(org_id: str, doc_type_slug: str, rok: int) -> str:
    """Zostaví hash-based URL pre daný typ a rok."""
    return f"{BASE_URL}/#/zverejnovanie/{SNV_CITY_SLUG}/{org_id}/{doc_type_slug}/{rok}"


def get_doc_type_slugs(typ: str) -> list[str]:
    """Vráti zoznam URL slugov pre zvolený typ dokumentov."""
    if typ == "all":
        return list(DOC_TYPES.keys())
    if typ == "faktury":
        return ["faktury-dodavatelske", "faktury-odberatelske"]
    if typ in DOC_TYPES:
        return [typ]
    return list(DOC_TYPES.keys())


def get_years(rok_arg: int | None) -> list[int]:
    """Vráti zoznam rokov na scrapovanie."""
    if rok_arg:
        return [rok_arg]
    # Predvolene posledné 3 roky + aktuálny
    return list(range(CURRENT_YEAR - 2, CURRENT_YEAR + 1))


# ---------------------------------------------------------------------------
# Hlavná funkcia
# ---------------------------------------------------------------------------

def scrape_vsetky_organizacie(
    keyword: str = "",
    doc_type: str = "all",
    rok_arg: int | None = None,
    max_pages: int = 10,
    headless: bool = True,
    scrape_details: bool = True,
    org_ids: list[str] | None = None,
) -> list[Dokument]:
    """Scrape všetky SNV organizácie v jednom browseri."""
    orgs = org_ids or list(SNV_ORGANIZACIE.keys())
    years = get_years(rok_arg)
    all_docs: list[Dokument] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = _make_context(p, browser)
        api_buf: list[dict] = []
        page = ctx.new_page()
        page.on("response", _make_api_handler(api_buf))

        try:
            for org_id in orgs:
                org_nazov = SNV_ORGANIZACIE.get(org_id, org_id)
                print(f"\n[ORG] {org_nazov} ({org_id})", file=sys.stderr)
                org_docs: list[Dokument] = []

                for rok in years:
                    for dtype_slug in get_doc_type_slugs(doc_type):
                        api_buf.clear()
                        docs = _scrape_url(
                            page, org_id, org_nazov, dtype_slug, rok,
                            keyword, max_pages, api_buf
                        )
                        org_docs.extend(docs)

                if scrape_details:
                    org_docs = _enrich_with_details(page, org_docs)

                org_docs = _filter_keyword(org_docs, keyword)
                print(f"  [✓] {len(org_docs)} dokumentov", file=sys.stderr)
                all_docs.extend(org_docs)

        except Exception as e:
            print(f"[!] Chyba: {e}", file=sys.stderr)
        finally:
            browser.close()

    return all_docs


def scrape_organizacia(
    org_id: str,
    org_nazov: str,
    keyword: str = "",
    doc_type: str = "all",
    rok_arg: int | None = None,
    max_pages: int = 10,
    headless: bool = True,
    scrape_details: bool = True,
) -> list[Dokument]:
    """Scrape jednu organizáciu."""
    years = get_years(rok_arg)
    all_docs: list[Dokument] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = _make_context(p, browser)
        api_buf: list[dict] = []
        page = ctx.new_page()
        page.on("response", _make_api_handler(api_buf))

        try:
            for rok in years:
                for dtype_slug in get_doc_type_slugs(doc_type):
                    api_buf.clear()
                    docs = _scrape_url(
                        page, org_id, org_nazov, dtype_slug, rok,
                        keyword, max_pages, api_buf
                    )
                    all_docs.extend(docs)

            if scrape_details:
                all_docs = _enrich_with_details(page, all_docs)

        except Exception as e:
            print(f"[!] Chyba: {e}", file=sys.stderr)
        finally:
            browser.close()

    return _filter_keyword(all_docs, keyword)


def _make_context(p, browser):
    return browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        # Desktop viewport – zabezpečí zobrazenie search poľa (na mobile chýba)
        viewport={"width": 1440, "height": 900},
        locale="sk-SK",
        extra_http_headers={
            "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        },
    )


def _make_api_handler(api_buf: list[dict]):
    def handle_response(response):
        try:
            ct = response.headers.get("content-type", "")
            if "application/json" not in ct:
                return
            url = response.url
            if not any(k in url for k in [
                "zmluv", "faktur", "objednav", "document", "contract",
                "invoice", "order", "api", "zverejn", "data",
            ]):
                return
            try:
                data = response.json()
                api_buf.append({"url": url, "status": response.status, "data": data})
                print(f"  [API] {url}", file=sys.stderr)
            except Exception:
                pass
        except Exception:
            pass
    return handle_response


# ---------------------------------------------------------------------------
# Scraping jednej URL (org + typ + rok)
# ---------------------------------------------------------------------------

def _scrape_url(
    page,
    org_id: str,
    org_nazov: str,
    dtype_slug: str,
    rok: int,
    keyword: str,
    max_pages: int,
    api_buf: list[dict],
) -> list[Dokument]:
    url = build_url(org_id, dtype_slug, rok)
    doc_type = DOC_TYPES.get(dtype_slug, dtype_slug)
    print(f"  [→] {dtype_slug}/{rok}: {url}", file=sys.stderr)

    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if resp and resp.status == 404:
            print(f"  [~] 404 – org/typ neexistuje", file=sys.stderr)
            return []
        if resp and resp.status == 403:
            print(f"  [~] 403 – prístup zamietnutý", file=sys.stderr)
            return []
    except Exception as e:
        print(f"  [!] Goto error: {e}", file=sys.stderr)
        return []

    # Počkaj na SPA render
    page.wait_for_timeout(3000)
    _log_page_info(page)

    # Vyhľadávanie (search pole viditeľné iba na PC viewporte)
    if keyword:
        _try_search(page, keyword)
        page.wait_for_timeout(2000)

    # Skús API odpovede zachytené počas načítania
    if api_buf:
        api_docs = _parse_api_responses(api_buf, doc_type, org_id, org_nazov, rok)
        if api_docs:
            print(f"  [API] {len(api_docs)} dokumentov", file=sys.stderr)
            api_docs.extend(_paginate_api(page, doc_type, org_id, org_nazov, rok, max_pages, api_buf))
            return _deduplicate(api_docs)

    # DOM scraping + stránkovanie
    docs: list[Dokument] = []
    for page_num in range(1, max_pages + 1):
        page_docs = _extract_from_page(page, doc_type, org_id, org_nazov, str(rok))
        if not page_docs:
            break
        docs.extend(page_docs)
        print(f"  [DOM] str.{page_num}: {len(page_docs)} dok.", file=sys.stderr)
        if not _go_next_page(page):
            break
        page.wait_for_timeout(1200)

    return _deduplicate(docs)


def _paginate_api(page, doc_type, org_id, org_nazov, rok, max_pages, api_buf) -> list[Dokument]:
    docs: list[Dokument] = []
    for _ in range(2, max_pages + 1):
        api_buf.clear()
        if not _go_next_page(page):
            break
        page.wait_for_timeout(1500)
        if api_buf:
            page_docs = _parse_api_responses(api_buf, doc_type, org_id, org_nazov, rok)
            if not page_docs:
                break
            docs.extend(page_docs)
        else:
            break
    return docs


# ---------------------------------------------------------------------------
# API parsing
# ---------------------------------------------------------------------------

def _parse_api_responses(
    api_buf: list[dict],
    doc_type: str,
    org_id: str,
    org_nazov: str,
    rok: int | str,
) -> list[Dokument]:
    docs: list[Dokument] = []
    for resp in api_buf:
        for item in _extract_items_from_json(resp.get("data", {})):
            doc = _map_api_item(item, doc_type, org_id, org_nazov, str(rok))
            if doc.nazov or doc.cislo:
                docs.append(doc)
    return docs


def _extract_items_from_json(data: Any) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["items", "data", "results", "records", "documents",
                    "zmluvy", "faktury", "objednavky", "content", "list",
                    "rows", "entries", "contracts", "invoices", "orders"]:
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                inner = _extract_items_from_json(val)
                if inner:
                    return inner
    return []


def _map_api_item(item: dict, doc_type: str, org_id: str, org_nazov: str, rok: str) -> Dokument:
    doc = Dokument(typ=doc_type, org_id=org_id, organizacia=org_nazov, rok=rok, raw=item)

    def g(*keys: str) -> str:
        for k in keys:
            v = item.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    doc.id_dokumentu      = g("id", "uuid", "documentId", "Id")
    doc.cislo             = g("number", "cislo", "contractNumber", "invoiceNumber", "orderNumber", "documentNumber", "Cislo", "No")
    doc.nazov             = g("subject", "name", "title", "nazov", "predmet", "Name", "Subject", "Title", "description")
    doc.popis             = g("description", "note", "popis", "Description", "longDescription")
    doc.dodavatel         = g("supplier", "supplierName", "vendor", "vendorName", "contractor", "dodavatel", "firma", "Supplier", "Vendor")
    doc.ico               = g("ico", "supplierIco", "vendorIco", "ICO", "supplierRegistrationNumber", "registrationNumber")
    doc.dic               = g("dic", "DIC", "taxId", "vatNumber", "taxNumber")
    doc.adresa_dodavatela = g("supplierAddress", "vendorAddress", "address", "adresa", "supplierCity")
    doc.objednavatel      = g("customer", "customerName", "buyer", "objednavatel", "odberatel")
    doc.oddelenie         = g("department", "oddelenie", "section", "unit", "Department", "division")
    doc.suma              = g("amount", "value", "price", "suma", "cena", "totalAmount", "totalPrice", "hodnota", "Amount", "Total")
    doc.suma_bez_dph      = g("amountWithoutVat", "priceWithoutVat", "sumaBezvDph", "netAmount", "netValue", "baseAmount")
    doc.mena              = g("currency", "mena", "Currency") or "EUR"
    doc.datum             = g("date", "signDate", "contractDate", "datum", "datumPodpisu", "issueDate", "orderDate", "Date", "signedDate")
    doc.datum_ucinnosti   = g("effectiveDate", "datumUcinnosti", "dueDate", "datumSplatnosti", "validFrom", "startDate")
    doc.datum_zverejnenia = g("publishedDate", "publicationDate", "datumZverejnenia", "createdAt", "publishDate", "publishedAt")
    doc.datum_platnosti_do = g("validTo", "expiryDate", "datumPlatnostiDo", "endDate", "expirationDate", "validUntil")
    doc.kategoria         = g("category", "kategoria", "type", "documentType", "Category", "Type")
    doc.podkategoria      = g("subcategory", "podkategoria", "subtype", "SubCategory")
    doc.stav              = g("status", "stav", "state", "Status", "State")
    doc.poznamka          = g("note", "remark", "comment", "poznamka", "Note", "Remark")

    if not doc.rok:
        doc.rok = rok

    url = g("url", "link", "detailUrl", "href", "Url", "detailLink")
    doc.url = url if url.startswith("http") else (BASE_URL + url if url else "")

    for fkey in ["files", "attachments", "documents", "subory", "prilohy", "Downloads", "attachedFiles"]:
        fval = item.get(fkey)
        if not isinstance(fval, list):
            continue
        for f in fval:
            if isinstance(f, str):
                doc.subory.append(f if f.startswith("http") else BASE_URL + f)
            elif isinstance(f, dict):
                furl = f.get("url") or f.get("href") or f.get("path") or f.get("link") or ""
                if furl:
                    doc.subory.append(furl if furl.startswith("http") else BASE_URL + furl)

    return doc


# ---------------------------------------------------------------------------
# DOM scraping
# ---------------------------------------------------------------------------

def _extract_from_page(page, doc_type: str, org_id: str, org_nazov: str, rok: str) -> list[Dokument]:
    base_fields = dict(org_id=org_id, organizacia=org_nazov, rok=rok)
    docs = _extract_from_tables(page, doc_type, base_fields)
    if docs:
        return docs
    docs = _extract_from_list(page, doc_type, base_fields)
    if docs:
        return docs
    docs = _extract_from_cards(page, doc_type, base_fields)
    return docs


def _extract_from_tables(page, doc_type: str, base_fields: dict) -> list[Dokument]:
    docs: list[Dokument] = []
    try:
        for table in page.locator("table").all():
            headers = [th.inner_text().strip().lower() for th in table.locator("th").all()]
            for row in table.locator("tbody tr").all():
                cells = row.locator("td").all()
                if not cells:
                    continue
                doc = Dokument(typ=doc_type, **base_fields)
                cell_texts = [c.inner_text().strip() for c in cells]

                for i, h in enumerate(headers):
                    if i >= len(cell_texts):
                        break
                    v = cell_texts[i]
                    if any(k in h for k in ["číslo", "cislo", "number", "č.", "poradové"]):
                        doc.cislo = v
                    elif any(k in h for k in ["predmet", "názov", "name", "subject", "popis", "opis"]):
                        doc.nazov = v
                    elif any(k in h for k in ["dodávateľ", "firma", "supplier", "vendor", "zhotoviteľ", "subjekt"]):
                        doc.dodavatel = v
                    elif "ičo" in h or h.strip() == "ico":
                        doc.ico = v
                    elif any(k in h for k in ["dič", "dic"]):
                        doc.dic = v
                    elif any(k in h for k in ["dátum účinnosti", "účinnosti", "effective", "splatnosti"]):
                        doc.datum_ucinnosti = v
                    elif any(k in h for k in ["dátum zverej", "zverejnenia", "zverejnen", "published"]):
                        doc.datum_zverejnenia = v
                    elif any(k in h for k in ["dátum podpisu", "podpisu", "sign", "uzatvoren", "vystaveni"]):
                        doc.datum = v
                    elif any(k in h for k in ["dátum", "date", "datum"]):
                        if not doc.datum:
                            doc.datum = v
                    elif any(k in h for k in ["suma bez", "bez dph", "základ", "net"]):
                        doc.suma_bez_dph = v
                    elif any(k in h for k in ["suma", "cena", "hodnota", "amount", "€", "eur", "price"]):
                        doc.suma = v
                    elif any(k in h for k in ["kategór", "category", "druh"]):
                        doc.kategoria = v
                    elif any(k in h for k in ["oddelenie", "útvar", "department", "referát"]):
                        doc.oddelenie = v
                    elif any(k in h for k in ["stav", "status"]):
                        doc.stav = v

                # Pozičný fallback
                if not doc.nazov and cell_texts:
                    doc.nazov = cell_texts[0]
                if not doc.dodavatel and len(cell_texts) >= 2:
                    doc.dodavatel = cell_texts[1]
                if not doc.datum and len(cell_texts) >= 3:
                    doc.datum = cell_texts[2]
                if not doc.suma and len(cell_texts) >= 4:
                    doc.suma = cell_texts[3]

                # URL z linkov v riadku
                for link in row.locator("a").all():
                    try:
                        href = link.get_attribute("href") or ""
                        if href:
                            doc.url = href if href.startswith("http") else BASE_URL + href
                            break
                    except Exception:
                        pass

                if doc.nazov or doc.cislo:
                    docs.append(doc)
    except Exception as e:
        print(f"  [~] Tabuľka: {e}", file=sys.stderr)
    return docs


def _extract_from_list(page, doc_type: str, base_fields: dict) -> list[Dokument]:
    docs: list[Dokument] = []
    try:
        selectors = [
            ".document-item", ".list-item", ".record-item",
            ".zmluva-item", ".faktura-item", ".objednavka-item",
            "[class*='document-row']", "[class*='contract-row']",
            "[class*='record']", "li[class*='item']", ".result-item",
            "[class*='document']", "[class*='invoice']", "[class*='order']",
        ]
        for sel in selectors:
            items = page.locator(sel).all()
            if not items:
                continue
            for item in items:
                doc = _parse_item_element(item, doc_type, base_fields)
                if doc.nazov or doc.cislo:
                    docs.append(doc)
            if docs:
                break
    except Exception as e:
        print(f"  [~] Zoznam: {e}", file=sys.stderr)
    return docs


def _extract_from_cards(page, doc_type: str, base_fields: dict) -> list[Dokument]:
    docs: list[Dokument] = []
    try:
        for sel in [".card", ".item-card", ".document-card", "[class*='card']", "article", ".tile"]:
            cards = page.locator(sel).all()
            if not cards:
                continue
            for card in cards:
                doc = _parse_item_element(card, doc_type, base_fields)
                if not doc.nazov:
                    for heading in ["h1", "h2", "h3", "h4", ".title", ".name"]:
                        try:
                            el = card.locator(heading)
                            if el.count() > 0:
                                doc.nazov = el.first.inner_text().strip()
                                break
                        except Exception:
                            pass
                if doc.nazov or doc.cislo:
                    docs.append(doc)
            if docs:
                break
    except Exception as e:
        print(f"  [~] Karty: {e}", file=sys.stderr)
    return docs


def _parse_item_element(item, doc_type: str, base_fields: dict) -> Dokument:
    doc = Dokument(typ=doc_type, **base_fields)

    # data-* atribúty
    for attr, fname in [
        ("data-id", "id_dokumentu"), ("data-number", "cislo"), ("data-name", "nazov"),
        ("data-supplier", "dodavatel"), ("data-ico", "ico"), ("data-amount", "suma"),
        ("data-date", "datum"), ("data-category", "kategoria"), ("data-status", "stav"),
    ]:
        try:
            v = item.get_attribute(attr)
            if v:
                setattr(doc, fname, v.strip())
        except Exception:
            pass

    # CSS class selektory
    for sel, fname in [
        (".cislo, .number, [class*='number']", "cislo"),
        (".nazov, .name, .title, .predmet, [class*='subject']", "nazov"),
        (".dodavatel, .supplier, .vendor, .firma, [class*='supplier']", "dodavatel"),
        (".ico, [class*='ico']", "ico"),
        (".suma, .amount, .price, .hodnota, [class*='amount']", "suma"),
        (".datum, .date, [class*='date']", "datum"),
        (".kategoria, .category, [class*='category']", "kategoria"),
        (".oddelenie, .department, [class*='department']", "oddelenie"),
        (".stav, .status, [class*='status']", "stav"),
        (".popis, .description, [class*='description']", "popis"),
    ]:
        if getattr(doc, fname):
            continue
        try:
            el = item.locator(sel)
            if el.count() > 0:
                setattr(doc, fname, el.first.inner_text().strip())
        except Exception:
            pass

    # Textový fallback
    if not doc.nazov:
        try:
            lines = [l.strip() for l in item.inner_text().strip().split("\n") if l.strip()]
            if lines:
                doc.nazov = lines[0]
            if len(lines) > 1 and not doc.dodavatel:
                doc.dodavatel = lines[1]
            if len(lines) > 2 and not doc.datum:
                doc.datum = lines[2]
            if len(lines) > 3 and not doc.suma:
                doc.suma = lines[3]
        except Exception:
            pass

    # Linky a PDF prílohy
    try:
        for link in item.locator("a").all():
            href = link.get_attribute("href") or ""
            if not href:
                continue
            if not href.startswith("http"):
                href = BASE_URL + href
            if any(x in href.lower() for x in [".pdf", "download", "priloha", "attachment"]):
                doc.subory.append(href)
            elif not doc.url:
                doc.url = href
    except Exception:
        pass

    return doc


# ---------------------------------------------------------------------------
# Detail stránky
# ---------------------------------------------------------------------------

LABEL_MAP: dict[str, str] = {
    "číslo zmluvy": "cislo", "číslo faktúry": "cislo", "číslo objednávky": "cislo",
    "číslo": "cislo", "number": "cislo",
    "predmet": "nazov", "predmet zmluvy": "nazov", "názov": "nazov",
    "subject": "nazov", "title": "nazov",
    "popis": "popis", "description": "popis",
    "poznámka": "poznamka", "note": "poznamka",
    "dodávateľ": "dodavatel", "zhotoviteľ": "dodavatel", "supplier": "dodavatel",
    "vendor": "dodavatel", "firma": "dodavatel", "obchodné meno": "dodavatel",
    "ičo": "ico", "ico": "ico", "ič": "ico",
    "dič": "dic", "dic": "dic",
    "adresa": "adresa_dodavatela",
    "objednávateľ": "objednavatel", "odberateľ": "objednavatel",
    "oddelenie": "oddelenie", "útvar": "oddelenie", "referát": "oddelenie",
    "organizačná jednotka": "oddelenie",
    "suma": "suma", "hodnota": "suma", "cena": "suma",
    "celková suma": "suma", "celková hodnota": "suma",
    "suma s dph": "suma", "cena s dph": "suma",
    "amount": "suma", "total": "suma",
    "suma bez dph": "suma_bez_dph", "cena bez dph": "suma_bez_dph",
    "základ dane": "suma_bez_dph",
    "mena": "mena", "currency": "mena",
    "dátum uzatvorenia": "datum", "dátum podpisu": "datum",
    "dátum vystavenia": "datum", "dátum objednávky": "datum", "date": "datum",
    "dátum účinnosti": "datum_ucinnosti", "účinnosť od": "datum_ucinnosti",
    "dátum splatnosti": "datum_ucinnosti",
    "dátum zverejnenia": "datum_zverejnenia", "zverejnené": "datum_zverejnenia",
    "platnosť do": "datum_platnosti_do", "dátum ukončenia": "datum_platnosti_do",
    "kategória": "kategoria", "category": "kategoria", "druh": "kategoria",
    "podkategória": "podkategoria",
    "rok": "rok", "year": "rok",
    "stav": "stav", "status": "stav",
}


def _enrich_with_details(page, docs: list[Dokument]) -> list[Dokument]:
    for i, doc in enumerate(docs):
        if not doc.url:
            continue
        try:
            print(f"  [→] Detail {i+1}/{len(docs)}: {doc.url}", file=sys.stderr)
            page.goto(doc.url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)
            _parse_detail_page(page, doc)
        except Exception as e:
            print(f"  [~] Detail: {e}", file=sys.stderr)
    return docs


def _parse_detail_page(page, doc: Dokument) -> None:
    # dl > dt + dd
    try:
        for dt in page.locator("dl dt").all():
            label = dt.inner_text().strip().lower().rstrip(":")
            dd = dt.evaluate_handle("el => el.nextElementSibling")
            if dd:
                val = page.evaluate("el => el ? el.innerText : ''", dd).strip()
                _set_field(doc, label, val)
    except Exception:
        pass

    # 2-stĺpcové tabuľky
    try:
        for row in page.locator("table tr").all():
            cells = row.locator("td, th").all()
            if len(cells) == 2:
                label = cells[0].inner_text().strip().lower().rstrip(":")
                val = cells[1].inner_text().strip()
                _set_field(doc, label, val)
    except Exception:
        pass

    # div páry label:value
    try:
        for sel in [".field", ".detail-field", ".info-row", ".data-row",
                    "[class*='field']", "[class*='detail-row']", "[class*='info-item']"]:
            items = page.locator(sel).all()
            if not items:
                continue
            for item in items:
                text = item.inner_text().strip()
                if ":" in text:
                    parts = text.split(":", 1)
                    _set_field(doc, parts[0].strip().lower(), parts[1].strip())
            if doc.dodavatel or doc.suma:
                break
    except Exception:
        pass

    # Konkrétne CSS triedy
    for sel, fname in [
        (".cislo, .contract-number, [class*='number']", "cislo"),
        (".nazov, .subject, .predmet, [class*='subject']", "nazov"),
        (".dodavatel, .supplier, [class*='supplier']", "dodavatel"),
        (".ico", "ico"),
        (".dic", "dic"),
        (".suma, .amount, [class*='amount']", "suma"),
        (".datum-ucinnosti, [class*='effective']", "datum_ucinnosti"),
        (".datum-zverejnenia, [class*='published']", "datum_zverejnenia"),
        (".kategoria, .category, [class*='category']", "kategoria"),
        (".oddelenie, .department, [class*='department']", "oddelenie"),
        (".stav, .status, [class*='status']", "stav"),
        (".popis, .description, [class*='description']", "popis"),
    ]:
        if getattr(doc, fname):
            continue
        try:
            el = page.locator(sel)
            if el.count() > 0:
                setattr(doc, fname, el.first.inner_text().strip())
        except Exception:
            pass

    # Prílohy / PDF súbory
    try:
        seen = set(doc.subory)
        for sel in [
            "a[href$='.pdf']", "a[href$='.PDF']",
            "a[href*='download']", "a[href*='priloha']",
            "a[href*='attachment']",
            ".attachment a", ".file-list a", ".download a",
            "[class*='attachment'] a", "[class*='download'] a",
        ]:
            for link in page.locator(sel).all():
                try:
                    href = link.get_attribute("href") or ""
                    if not href:
                        continue
                    if not href.startswith("http"):
                        href = BASE_URL + href
                    if href not in seen:
                        doc.subory.append(href)
                        seen.add(href)
                except Exception:
                    pass
    except Exception:
        pass


def _set_field(doc: Dokument, label: str, val: str) -> None:
    if not val:
        return
    fname = LABEL_MAP.get(label.strip())
    if fname and not getattr(doc, fname, ""):
        setattr(doc, fname, val)


# ---------------------------------------------------------------------------
# Pomocné funkcie
# ---------------------------------------------------------------------------

def _filter_keyword(docs: list[Dokument], keyword: str) -> list[Dokument]:
    if not keyword:
        return docs
    kw = keyword.lower()
    return [
        d for d in docs
        if kw in d.nazov.lower()
        or kw in d.dodavatel.lower()
        or kw in d.popis.lower()
        or kw in d.kategoria.lower()
        or kw in d.cislo.lower()
        or kw in d.ico.lower()
    ]


def _log_page_info(page) -> None:
    try:
        print(f"  [i] {page.title()} | {page.url}", file=sys.stderr)
    except Exception:
        pass


def _try_search(page, keyword: str) -> bool:
    """Pokus o vyplnenie search poľa – viditeľné iba pri desktop viewporte (≥1024px)."""
    selectors = [
        'input[type="search"]',
        'input[placeholder*="hľadaj" i]',
        'input[placeholder*="vyhľadaj" i]',
        'input[placeholder*="search" i]',
        'input[placeholder*="filter" i]',
        'input[placeholder*="zadaj" i]',
        'input[name="q"]',
        'input[name="search"]',
        'input[name="keyword"]',
        '.search-input input',
        '#search-input',
        '#keyword',
        '.filter input',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.clear()
                loc.first.fill(keyword)
                loc.first.press("Enter")
                print(f"  [✓] Search: '{keyword}' ({sel})", file=sys.stderr)
                return True
        except Exception:
            continue

    # Submit tlačidlo po vyplnení
    for sel in selectors[:6]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.fill(keyword)
                for btn in ['button[type="submit"]', 'button:text("Hľadaj")',
                            'button:text("Vyhľadať")', '.search-btn', '.btn-search']:
                    if page.locator(btn).count() > 0:
                        page.locator(btn).first.click()
                        return True
        except Exception:
            continue

    print("  [~] Search pole nenájdené (filter bude klientsky).", file=sys.stderr)
    return False


def _go_next_page(page) -> bool:
    for sel in [
        'a[aria-label="Next page"]', 'a[aria-label="Ďalej"]',
        'a:text-is("Ďalej")', 'a:text-is("»")', 'a:text-is(">")',
        ".pagination .next a", ".pagination li.next a", "[rel='next']",
        "a.page-next", ".next-page",
        'button:text-is("Ďalej")', 'button[aria-label="Next"]',
        'button:text-is(">")', 'button:text-is("»")',
    ]:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_enabled() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                return True
        except Exception:
            continue
    return False


def _deduplicate(docs: list[Dokument]) -> list[Dokument]:
    seen: set[str] = set()
    result: list[Dokument] = []
    for doc in docs:
        key = doc.url or f"{doc.typ}|{doc.cislo}|{doc.nazov}|{doc.dodavatel}|{doc.rok}"
        if key not in seen:
            seen.add(key)
            result.append(doc)
    return result


# ---------------------------------------------------------------------------
# Zobrazenie výsledkov
# ---------------------------------------------------------------------------

DOC_TYPE_LABEL: dict[str, str] = {
    "zmluvy": "Zmluvy",
    "faktury": "Fakt. dod.",
    "faktury-odberatelske": "Fakt. odb.",
    "objednavky": "Objednávky",
}


def display_results(docs: list[Dokument], output_format: str = "table") -> None:
    if not docs:
        print("\nŽiadne výsledky nenájdené.")
        return

    if output_format == "json":
        def to_dict(d: Dokument) -> dict:
            r = asdict(d)
            r.pop("raw", None)
            return {k: v for k, v in r.items() if v or (isinstance(v, list) and v)}
        print(json.dumps([to_dict(d) for d in docs], ensure_ascii=False, indent=2))
        return

    if output_format == "csv":
        import csv, io
        fields = [
            "organizacia", "rok", "typ", "cislo", "nazov",
            "dodavatel", "ico", "dic", "adresa_dodavatela",
            "suma", "suma_bez_dph", "mena",
            "datum", "datum_ucinnosti", "datum_zverejnenia", "datum_platnosti_do",
            "kategoria", "oddelenie", "stav",
            "objednavatel", "popis", "poznamka", "url",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for d in docs:
            row = asdict(d)
            row.pop("raw", None)
            row["subory"] = " | ".join(row.get("subory", []))
            writer.writerow(row)
        print(buf.getvalue())
        return

    # Tabulkový formát
    W_ORG = 18
    W_ROK = 5
    W_TYP = 11
    W_CISLO = 16
    W_NAZOV = 34
    W_DODAVATEL = 24
    W_ICO = 11
    W_DATUM = 11
    W_SUMA = 14
    total_w = W_ORG + W_ROK + W_TYP + W_CISLO + W_NAZOV + W_DODAVATEL + W_ICO + W_DATUM + W_SUMA + 8

    print(f"\n{'='*total_w}")
    print(f"  Nájdených: {len(docs)} dokumentov – Spišská Nová Ves")
    print(f"{'='*total_w}")
    hdr = (
        f"{'Organizácia':<{W_ORG}} {'Rok':<{W_ROK}} {'Typ':<{W_TYP}} {'Číslo':<{W_CISLO}} "
        f"{'Názov':<{W_NAZOV}} {'Dodávateľ':<{W_DODAVATEL}} "
        f"{'IČO':<{W_ICO}} {'Dátum':<{W_DATUM}} {'Suma':<{W_SUMA}}"
    )
    print(hdr)
    print("-" * total_w)

    by_org: dict[str, list[Dokument]] = {}
    for d in docs:
        by_org.setdefault(d.organizacia or d.org_id, []).append(d)

    indent = " " * (W_ORG + W_ROK + W_TYP + 3)

    for org_name, org_docs in by_org.items():
        print(f"\n  === {org_name} ({len(org_docs)}) ===")
        for d in org_docs:
            org_s = (d.organizacia[:W_ORG-2] + "..") if len(d.organizacia) > W_ORG else d.organizacia
            typ_s = DOC_TYPE_LABEL.get(d.typ, d.typ)[:W_TYP]
            cislo_s = (d.cislo[:W_CISLO-2] + "..") if len(d.cislo) > W_CISLO else d.cislo
            nazov_s = (d.nazov[:W_NAZOV-2] + "..") if len(d.nazov) > W_NAZOV else d.nazov
            dod_s = (d.dodavatel[:W_DODAVATEL-2] + "..") if len(d.dodavatel) > W_DODAVATEL else d.dodavatel
            print(
                f"{org_s:<{W_ORG}} {d.rok:<{W_ROK}} {typ_s:<{W_TYP}} {cislo_s:<{W_CISLO}} "
                f"{nazov_s:<{W_NAZOV}} {dod_s:<{W_DODAVATEL}} "
                f"{d.ico:<{W_ICO}} {d.datum:<{W_DATUM}} {d.suma:<{W_SUMA}}"
            )
            extra = []
            if d.datum_ucinnosti:
                extra.append(f"Účinnosť: {d.datum_ucinnosti}")
            if d.datum_zverejnenia:
                extra.append(f"Zverejnené: {d.datum_zverejnenia}")
            if d.datum_platnosti_do:
                extra.append(f"Platí do: {d.datum_platnosti_do}")
            if d.kategoria:
                extra.append(f"Kat: {d.kategoria}")
            if d.oddelenie:
                extra.append(f"Odd: {d.oddelenie}")
            if d.stav:
                extra.append(f"Stav: {d.stav}")
            if d.suma_bez_dph:
                extra.append(f"Bez DPH: {d.suma_bez_dph}")
            if d.dic:
                extra.append(f"DIČ: {d.dic}")
            if extra:
                print(f"{indent}{' | '.join(extra)}")
            if d.url:
                print(f"{indent}URL: {d.url}")
            for f in d.subory:
                print(f"{indent}PDF: {f}")

    print(f"\n{'='*total_w}\n")


# ---------------------------------------------------------------------------
# Hlavný program
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="digitalnemesto_scraper",
        description=(
            "Scraper pre digitalnemesto.sk – Spišská Nová Ves a organizácie\n"
            f"URL: /#/zverejnovanie/{SNV_CITY_SLUG}/{{org-id}}/{{typ}}/{{rok}}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Príkladné príkazy:
  python digitalnemesto_scraper.py                           # všetky org, typy, roky
  python digitalnemesto_scraper.py --org mesto               # iba Mesto SNV
  python digitalnemesto_scraper.py --org ts                  # Technické služby
  python digitalnemesto_scraper.py --rok {CURRENT_YEAR}                # iba tento rok
  python digitalnemesto_scraper.py --typ zmluvy --rok {CURRENT_YEAR}   # zmluvy {CURRENT_YEAR}
  python digitalnemesto_scraper.py --keyword stavba          # filter kľúčovým slovom
  python digitalnemesto_scraper.py --format json             # JSON so všetkými poliami
  python digitalnemesto_scraper.py --format csv > data.csv   # CSV export
  python digitalnemesto_scraper.py --zoznam-org              # vypíše org SNV
  python digitalnemesto_scraper.py --bez-detailov            # rýchlejšie, menej polí
        """,
    )
    parser.add_argument(
        "--org", "-o",
        help="Slug alebo skratka organizácie (mesto, ts, mks, ...). Bez tohto parametra = všetky org SNV.",
    )
    parser.add_argument("--keyword", "-k", help="Kľúčové slovo pre filter výsledkov")
    parser.add_argument(
        "--typ", "-t",
        choices=["zmluvy", "faktury", "faktury-odberatelske", "objednavky", "all"],
        default="all",
        metavar="TYP",
        help="Typ: zmluvy | faktury | faktury-odberatelske | objednavky | all (default: all)",
    )
    parser.add_argument(
        "--rok", "-r",
        type=int,
        metavar="ROK",
        help=f"Rok dokumentov (napr. {CURRENT_YEAR}). Bez parametra = posledné 3 roky + aktuálny.",
    )
    parser.add_argument(
        "--stranky", "-s",
        type=int, default=10, metavar="N",
        help="Max počet stránok na typ/org/rok (default: 10)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["table", "json", "csv"],
        default="table",
        help="Formát výstupu: table | json | csv (default: table)",
    )
    parser.add_argument(
        "--zoznam-org",
        action="store_true",
        help="Zobrazí zoznam organizácií SNV na portáli",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Zobrazí okno prehliadača – desktop viewport (vždy ≥1440px pre search pole)",
    )
    parser.add_argument(
        "--bez-detailov",
        action="store_true",
        help="Preskočí detail stránky – rýchlejšie, ale menej polí (IČO, PDF...)",
    )

    args = parser.parse_args()

    if args.zoznam_org:
        print(f"\nOrganizácie Spišskej Novej Vsi na digitalnemesto.sk")
        print(f"URL pattern: {BASE_URL}/#/zverejnovanie/{SNV_CITY_SLUG}/{{org-id}}/{{typ}}/{{rok}}")
        print(f"\n  {'Skratka':<12} {'org-id':<35} Názov")
        print("-" * 75)
        for org_id, name in SNV_ORGANIZACIE.items():
            skratka = next((k for k, v in ORG_SKRATKY.items() if v == org_id), "")
            print(f"  {skratka:<12} {org_id:<35} {name}")
        print("\nTip: Ak org nie je v zozname, zadaj org-id priamo: --org <org-id>")
        print(f"     Napr. --org tsspiskanovaves\n")
        return

    headless = not args.visible
    scrape_details = not args.bez_detailov
    keyword = args.keyword or ""
    doc_type = args.typ

    years = get_years(args.rok)
    print(
        f"[→] SNV | org: {args.org or 'všetky'} | typ: {doc_type} "
        f"| rok: {args.rok or years} | keyword: '{keyword}'",
        file=sys.stderr,
    )

    if args.org:
        org_id = ORG_SKRATKY.get(args.org, args.org)
        if not any(org_id.startswith(p) for p in ["spisk", "mu", "ts", "mks", "mkc", "kni", "bh", "soc"]):
            pass  # nechaj ako je – môže byť ľubovoľný slug
        org_nazov = SNV_ORGANIZACIE.get(org_id, org_id)
        docs = scrape_organizacia(
            org_id=org_id,
            org_nazov=org_nazov,
            keyword=keyword,
            doc_type=doc_type,
            rok_arg=args.rok,
            max_pages=args.stranky,
            headless=headless,
            scrape_details=scrape_details,
        )
    else:
        docs = scrape_vsetky_organizacie(
            keyword=keyword,
            doc_type=doc_type,
            rok_arg=args.rok,
            max_pages=args.stranky,
            headless=headless,
            scrape_details=scrape_details,
        )

    display_results(docs, output_format=args.format)


if __name__ == "__main__":
    main()
