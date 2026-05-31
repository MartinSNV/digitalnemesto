#!/usr/bin/env python3
"""
Scraper pre digitalnemesto.sk – Spišská Nová Ves a jej organizácie
Zberá všetky dostupné údaje o dokumentoch (zmluvy, faktúry, objednávky).

Pouzitie:
  python digitalnemesto_scraper.py                          # SNV - všetky org, všetky typy
  python digitalnemesto_scraper.py --org mesto              # iba mestský úrad
  python digitalnemesto_scraper.py --keyword stavba         # filter kľúčovým slovom
  python digitalnemesto_scraper.py --typ zmluvy             # iba zmluvy
  python digitalnemesto_scraper.py --format json            # JSON výstup
  python digitalnemesto_scraper.py --zoznam-org             # vypíše dostupné organizácie
"""

import argparse
import json
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Nainštalujte playwright: pip install playwright && playwright install chromium", file=sys.stderr)
    sys.exit(1)


BASE_URL = "https://www.digitalnemesto.sk"

# Všetky organizácie Spišskej Novej Vsi na portáli digitalnemesto.sk
# Kľúč = slug používaný v URL, Hodnota = zobrazovaný názov
SNV_ORGANIZACIE: dict[str, str] = {
    "spiska-nova-ves": "Mesto Spišská Nová Ves",
    "spiska-nova-ves-mestsky-urad": "Mestský úrad Spišská Nová Ves",
    "spiska-nova-ves-ts": "Technické služby Spišská Nová Ves",
    "spiska-nova-ves-mks": "Mestské kultúrne stredisko SNV",
    "spiska-nova-ves-mkc": "Mestské kultúrne centrum SNV",
    "spiska-nova-ves-kniznica": "Mestská knižnica Spišská Nová Ves",
    "spiska-nova-ves-bh": "Bytové hospodárstvo SNV",
    "spiska-nova-ves-skola": "ZŠ Spišská Nová Ves",
    "spiska-nova-ves-ms": "MŠ Spišská Nová Ves",
    "spiska-nova-ves-szm": "Správa zdravotníckych zariadení",
    "spiska-nova-ves-sport": "Športové zariadenia SNV",
    "spiska-nova-ves-socialne": "Sociálne centrum SNV",
}

# Skratky pre --org parameter
ORG_SKRATKY: dict[str, str] = {
    "mesto": "spiska-nova-ves",
    "mu": "spiska-nova-ves-mestsky-urad",
    "ts": "spiska-nova-ves-ts",
    "mks": "spiska-nova-ves-mks",
    "mkc": "spiska-nova-ves-mkc",
    "kniznica": "spiska-nova-ves-kniznica",
    "bh": "spiska-nova-ves-bh",
}


@dataclass
class Dokument:
    # Organizácia / zdroj
    organizacia: str = ""          # názov organizácie (SNV entita)
    org_slug: str = ""             # slug organizácie

    # Základné identifikačné údaje
    typ: str = ""                  # zmluva / faktura / objednavka
    cislo: str = ""                # číslo dokumentu
    id_dokumentu: str = ""         # interné ID na portáli

    # Predmet / popis
    nazov: str = ""                # predmet / názov zmluvy
    popis: str = ""                # rozšírený popis

    # Zmluvná strana – dodávateľ / zhotoviteľ
    dodavatel: str = ""            # názov firmy / osoby
    ico: str = ""                  # IČO dodávateľa
    dic: str = ""                  # DIČ dodávateľa
    adresa_dodavatela: str = ""    # adresa dodávateľa

    # Objednávateľ / odberateľ
    objednavatel: str = ""         # mestský úrad / organizácia
    oddelenie: str = ""            # oddelenie / referát

    # Finančné údaje
    suma: str = ""                 # celková hodnota vrátane DPH
    suma_bez_dph: str = ""         # hodnota bez DPH
    mena: str = ""                 # mena (EUR)

    # Dátumy
    datum: str = ""                # hlavný dátum (podpis / vystavenie)
    datum_ucinnosti: str = ""      # dátum účinnosti / splatnosti
    datum_zverejnenia: str = ""    # dátum zverejnenia na portáli
    datum_platnosti_do: str = ""   # platnosť do

    # Kategorizácia
    kategoria: str = ""            # kategória dokumentu
    podkategoria: str = ""         # podkategória
    rok: str = ""                  # rok dokumentu
    stav: str = ""                 # stav (aktívna, ukončená, ...)

    # Súbory a linky
    url: str = ""                  # URL detail stránky
    subory: list[str] = field(default_factory=list)  # linky na PDF/prílohy

    # Ďalšie metadáta
    poznamka: str = ""             # poznámka / doplňujúce info
    raw: dict[str, Any] = field(default_factory=dict)  # surové dáta z API


# ---------------------------------------------------------------------------
# Hlavná funkcia
# ---------------------------------------------------------------------------

def scrape_organizacia(
    org_slug: str,
    org_nazov: str,
    keyword: str = "",
    doc_type: str = "all",
    max_pages: int = 10,
    headless: bool = True,
    scrape_details: bool = True,
) -> list[Dokument]:
    """Scrape všetky dokumenty jednej organizácie."""
    docs: list[Dokument] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="sk-SK",
            extra_http_headers={
                "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )

        api_responses: list[dict] = []

        def handle_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "application/json" in ct and any(
                    kw in response.url
                    for kw in ["zmluv", "faktur", "objednav", "document", "contract", "invoice", "api"]
                ):
                    try:
                        data = response.json()
                        api_responses.append({"url": response.url, "data": data})
                        print(f"[API] {response.url}", file=sys.stderr)
                    except Exception:
                        pass
            except Exception:
                pass

        page = context.new_page()
        page.on("response", handle_response)

        try:
            for dtype in _get_doc_types(doc_type):
                api_responses.clear()
                type_docs = _scrape_doc_type(
                    page, org_slug, dtype, keyword, max_pages, api_responses
                )
                # Nastav organizáciu na každom dokumente
                for d in type_docs:
                    d.organizacia = org_nazov
                    d.org_slug = org_slug
                docs.extend(type_docs)

            if scrape_details:
                docs = _enrich_with_details(page, docs)

        except PlaywrightTimeoutError:
            print("[!] Timeout.", file=sys.stderr)
        except Exception as e:
            print(f"[!] Chyba: {e}", file=sys.stderr)
        finally:
            browser.close()

    if keyword:
        kw = keyword.lower()
        docs = [
            d for d in docs
            if kw in d.nazov.lower()
            or kw in d.dodavatel.lower()
            or kw in d.popis.lower()
            or kw in d.kategoria.lower()
            or kw in d.cislo.lower()
        ]

    return docs


def scrape_vsetky_organizacie(
    keyword: str = "",
    doc_type: str = "all",
    max_pages: int = 10,
    headless: bool = True,
    scrape_details: bool = True,
    org_slugs: list[str] | None = None,
) -> list[Dokument]:
    """Scrape všetky SNV organizácie postupne (jeden browser)."""
    orgs = org_slugs or list(SNV_ORGANIZACIE.keys())
    all_docs: list[Dokument] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="sk-SK",
            extra_http_headers={
                "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )

        api_responses: list[dict] = []

        def handle_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "application/json" in ct and any(
                    kw in response.url
                    for kw in ["zmluv", "faktur", "objednav", "document", "api"]
                ):
                    try:
                        data = response.json()
                        api_responses.append({"url": response.url, "data": data})
                        print(f"[API] {response.url}", file=sys.stderr)
                    except Exception:
                        pass
            except Exception:
                pass

        page = context.new_page()
        page.on("response", handle_response)

        try:
            for org_slug in orgs:
                org_nazov = SNV_ORGANIZACIE.get(org_slug, org_slug)
                print(f"\n[ORG] {org_nazov} ({org_slug})", file=sys.stderr)

                org_docs: list[Dokument] = []
                for dtype in _get_doc_types(doc_type):
                    api_responses.clear()
                    type_docs = _scrape_doc_type(
                        page, org_slug, dtype, keyword, max_pages, api_responses
                    )
                    for d in type_docs:
                        d.organizacia = org_nazov
                        d.org_slug = org_slug
                    org_docs.extend(type_docs)

                if scrape_details:
                    org_docs = _enrich_with_details(page, org_docs)

                if keyword:
                    kw = keyword.lower()
                    org_docs = [
                        d for d in org_docs
                        if kw in d.nazov.lower()
                        or kw in d.dodavatel.lower()
                        or kw in d.popis.lower()
                        or kw in d.kategoria.lower()
                        or kw in d.cislo.lower()
                    ]

                print(f"[✓] {org_nazov}: {len(org_docs)} dokumentov", file=sys.stderr)
                all_docs.extend(org_docs)

        except PlaywrightTimeoutError:
            print("[!] Timeout.", file=sys.stderr)
        except Exception as e:
            print(f"[!] Chyba: {e}", file=sys.stderr)
        finally:
            browser.close()

    return all_docs


# ---------------------------------------------------------------------------
# Scraping jedného typu dokumentov
# ---------------------------------------------------------------------------

def _scrape_doc_type(
    page,
    org_slug: str,
    dtype: str,
    keyword: str,
    max_pages: int,
    api_responses: list[dict],
) -> list[Dokument]:
    docs: list[Dokument] = []
    section_map = {"zmluvy": "zmluvy", "faktury": "faktury", "objednavky": "objednavky"}
    section = section_map[dtype]
    direct_url = f"{BASE_URL}/mesto/{org_slug}/{section}"

    print(f"  [→] {dtype}: {direct_url}", file=sys.stderr)
    try:
        resp = page.goto(direct_url, wait_until="domcontentloaded", timeout=30000)
        if resp and resp.status in (404, 403):
            # Fallback: hlavná stránka + tab
            city_url = f"{BASE_URL}/mesto/{org_slug}/"
            page.goto(city_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            _navigate_to_section(page, dtype)
    except Exception as e:
        print(f"  [!] {dtype}: {e}", file=sys.stderr)
        return docs

    page.wait_for_timeout(2500)
    _log_page_info(page)

    if keyword:
        _try_search(page, keyword)
        page.wait_for_timeout(2000)

    # Skús API
    if api_responses:
        api_docs = _parse_api_responses(api_responses, dtype)
        if api_docs:
            print(f"  [API] {dtype}: {len(api_docs)} z API", file=sys.stderr)
            docs.extend(api_docs)
            docs.extend(_paginate_api(page, dtype, max_pages, api_responses))
            return _deduplicate(docs)

    # DOM scraping
    for page_num in range(1, max_pages + 1):
        page_docs = _extract_from_page(page, dtype)
        if not page_docs:
            break
        docs.extend(page_docs)
        print(f"  [i] {dtype} str.{page_num}: {len(page_docs)} dok.", file=sys.stderr)
        if not _go_next_page(page):
            break
        page.wait_for_timeout(1200)

    return _deduplicate(docs)


def _paginate_api(page, dtype: str, max_pages: int, api_responses: list[dict]) -> list[Dokument]:
    docs: list[Dokument] = []
    for _ in range(2, max_pages + 1):
        api_responses.clear()
        if not _go_next_page(page):
            break
        page.wait_for_timeout(1500)
        if api_responses:
            page_docs = _parse_api_responses(api_responses, dtype)
            if not page_docs:
                break
            docs.extend(page_docs)
        else:
            break
    return docs


# ---------------------------------------------------------------------------
# API parsing
# ---------------------------------------------------------------------------

def _parse_api_responses(api_responses: list[dict], dtype: str) -> list[Dokument]:
    docs: list[Dokument] = []
    for resp in api_responses:
        for item in _extract_items_from_json(resp.get("data", {})):
            doc = _map_api_item(item, dtype)
            if doc.nazov or doc.cislo:
                docs.append(doc)
    return docs


def _extract_items_from_json(data: Any) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["items", "data", "results", "records", "documents",
                    "zmluvy", "faktury", "objednavky", "content", "list"]:
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                inner = _extract_items_from_json(val)
                if inner:
                    return inner
    return []


def _map_api_item(item: dict, dtype: str) -> Dokument:
    doc = Dokument(typ=dtype, raw=item)

    def get(*keys: str) -> str:
        for k in keys:
            v = item.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    doc.id_dokumentu   = get("id", "uuid", "documentId")
    doc.cislo          = get("number", "cislo", "contractNumber", "invoiceNumber", "orderNumber", "documentNumber")
    doc.nazov          = get("subject", "name", "title", "nazov", "predmet", "description", "Name", "Subject")
    doc.popis          = get("description", "note", "popis", "Description")
    doc.dodavatel      = get("supplier", "supplierName", "vendor", "vendorName", "contractor", "dodavatel", "firma")
    doc.ico            = get("ico", "supplierIco", "vendorIco", "ICO", "supplierRegistrationNumber")
    doc.dic            = get("dic", "DIC", "taxId", "vatNumber")
    doc.adresa_dodavatela = get("supplierAddress", "vendorAddress", "address", "adresa")
    doc.objednavatel   = get("customer", "customerName", "buyer", "objednavatel")
    doc.oddelenie      = get("department", "oddelenie", "section", "unit")
    doc.suma           = get("amount", "value", "price", "suma", "cena", "totalAmount", "hodnota")
    doc.suma_bez_dph   = get("amountWithoutVat", "priceWithoutVat", "sumaBezvDph", "netAmount")
    doc.mena           = get("currency", "mena") or "EUR"
    doc.datum          = get("date", "signDate", "contractDate", "datum", "datumPodpisu", "issueDate", "orderDate")
    doc.datum_ucinnosti  = get("effectiveDate", "datumUcinnosti", "dueDate", "datumSplatnosti", "validFrom")
    doc.datum_zverejnenia = get("publishedDate", "publicationDate", "datumZverejnenia", "createdAt")
    doc.datum_platnosti_do = get("validTo", "expiryDate", "datumPlatnostiDo", "endDate")
    doc.kategoria      = get("category", "kategoria", "type", "documentType")
    doc.podkategoria   = get("subcategory", "podkategoria", "subtype")
    doc.rok            = get("year", "rok")
    doc.stav           = get("status", "stav", "state")
    doc.poznamka       = get("note", "remark", "comment", "poznamka")

    url = get("url", "link", "detailUrl", "href")
    doc.url = url if url.startswith("http") else (BASE_URL + url if url else "")

    for fkey in ["files", "attachments", "documents", "subory", "prilohy"]:
        fval = item.get(fkey)
        if isinstance(fval, list):
            for f in fval:
                if isinstance(f, str):
                    doc.subory.append(f if f.startswith("http") else BASE_URL + f)
                elif isinstance(f, dict):
                    furl = f.get("url") or f.get("href") or f.get("path") or ""
                    if furl:
                        doc.subory.append(furl if furl.startswith("http") else BASE_URL + furl)

    return doc


# ---------------------------------------------------------------------------
# DOM scraping
# ---------------------------------------------------------------------------

def _extract_from_page(page, doc_type: str) -> list[Dokument]:
    docs = _extract_from_tables(page, doc_type)
    if docs:
        return docs
    docs = _extract_from_list(page, doc_type)
    if docs:
        return docs
    docs = _extract_from_cards(page, doc_type)
    return docs


def _extract_from_tables(page, doc_type: str) -> list[Dokument]:
    docs: list[Dokument] = []
    try:
        for table in page.locator("table").all():
            headers = [th.inner_text().strip().lower() for th in table.locator("th").all()]
            for row in table.locator("tbody tr").all():
                cells = row.locator("td").all()
                if not cells:
                    continue
                doc = Dokument(typ=doc_type)
                cell_texts = [c.inner_text().strip() for c in cells]

                for i, h in enumerate(headers):
                    if i >= len(cell_texts):
                        break
                    v = cell_texts[i]
                    if any(k in h for k in ["číslo", "cislo", "number", "č."]):
                        doc.cislo = v
                    elif any(k in h for k in ["názov", "predmet", "name", "subject", "opis"]):
                        doc.nazov = v
                    elif any(k in h for k in ["dodávateľ", "firma", "supplier", "vendor", "subjekt"]):
                        doc.dodavatel = v
                    elif "ičo" in h or h == "ico":
                        doc.ico = v
                    elif any(k in h for k in ["dátum účinnosti", "účinnosti", "effective"]):
                        doc.datum_ucinnosti = v
                    elif any(k in h for k in ["dátum zverej", "zverejnenia", "published"]):
                        doc.datum_zverejnenia = v
                    elif any(k in h for k in ["dátum", "date", "datum"]):
                        if not doc.datum:
                            doc.datum = v
                    elif any(k in h for k in ["suma", "cena", "hodnota", "amount", "€", "eur"]):
                        if "bez" in h or "net" in h:
                            doc.suma_bez_dph = v
                        else:
                            doc.suma = v
                    elif any(k in h for k in ["kategór", "category"]):
                        doc.kategoria = v
                    elif any(k in h for k in ["oddelenie", "útvar", "department"]):
                        doc.oddelenie = v
                    elif any(k in h for k in ["stav", "status"]):
                        doc.stav = v
                    elif any(k in h for k in ["rok", "year"]):
                        doc.rok = v

                if not doc.nazov and cell_texts:
                    doc.nazov = cell_texts[0]
                if not doc.dodavatel and len(cell_texts) >= 2:
                    doc.dodavatel = cell_texts[1]
                if not doc.datum and len(cell_texts) >= 3:
                    doc.datum = cell_texts[2]
                if not doc.suma and len(cell_texts) >= 4:
                    doc.suma = cell_texts[3]

                links = row.locator("a").all()
                if links:
                    try:
                        href = links[0].get_attribute("href") or ""
                        if href:
                            doc.url = href if href.startswith("http") else BASE_URL + href
                    except Exception:
                        pass

                if doc.nazov or doc.cislo:
                    docs.append(doc)
    except Exception as e:
        print(f"  [~] Tabuľka: {e}", file=sys.stderr)
    return docs


def _extract_from_list(page, doc_type: str) -> list[Dokument]:
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
                doc = _parse_item_element(item, doc_type)
                if doc.nazov or doc.cislo:
                    docs.append(doc)
            if docs:
                break
    except Exception as e:
        print(f"  [~] Zoznam: {e}", file=sys.stderr)
    return docs


def _extract_from_cards(page, doc_type: str) -> list[Dokument]:
    docs: list[Dokument] = []
    try:
        for sel in [".card", ".item-card", ".document-card", "[class*='card']", "article", ".tile"]:
            cards = page.locator(sel).all()
            if not cards:
                continue
            for card in cards:
                doc = _parse_item_element(card, doc_type)
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


def _parse_item_element(item, doc_type: str) -> Dokument:
    doc = Dokument(typ=doc_type)

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
    # Číslo
    "číslo zmluvy": "cislo", "číslo faktúry": "cislo", "číslo objednávky": "cislo",
    "číslo": "cislo", "number": "cislo", "contract number": "cislo",
    # Predmet
    "predmet": "nazov", "predmet zmluvy": "nazov", "názov": "nazov",
    "subject": "nazov", "title": "nazov",
    # Popis
    "popis": "popis", "description": "popis",
    "poznámka": "poznamka", "note": "poznamka",
    # Dodávateľ
    "dodávateľ": "dodavatel", "zhotoviteľ": "dodavatel", "supplier": "dodavatel",
    "vendor": "dodavatel", "firma": "dodavatel", "obchodné meno": "dodavatel",
    # IČO / DIČ
    "ičo": "ico", "ico": "ico", "ič": "ico",
    "dič": "dic", "dic": "dic", "tax id": "dic",
    "adresa": "adresa_dodavatela", "address": "adresa_dodavatela",
    # Objednávateľ
    "objednávateľ": "objednavatel", "odberateľ": "objednavatel",
    "customer": "objednavatel", "buyer": "objednavatel",
    "oddelenie": "oddelenie", "útvar": "oddelenie", "department": "oddelenie",
    "referát": "oddelenie", "organizačná jednotka": "oddelenie",
    # Financie
    "suma": "suma", "hodnota": "suma", "cena": "suma",
    "celková suma": "suma", "celková hodnota": "suma",
    "suma s dph": "suma", "cena s dph": "suma",
    "amount": "suma", "total": "suma", "price": "suma",
    "suma bez dph": "suma_bez_dph", "cena bez dph": "suma_bez_dph",
    "základ dane": "suma_bez_dph", "net amount": "suma_bez_dph",
    "mena": "mena", "currency": "mena",
    # Dátumy
    "dátum uzatvorenia": "datum", "dátum podpisu": "datum",
    "dátum vystavenia": "datum", "dátum objednávky": "datum",
    "date": "datum", "sign date": "datum",
    "dátum účinnosti": "datum_ucinnosti", "účinnosť od": "datum_ucinnosti",
    "effective date": "datum_ucinnosti", "dátum splatnosti": "datum_ucinnosti",
    "dátum zverejnenia": "datum_zverejnenia", "zverejnené": "datum_zverejnenia",
    "published": "datum_zverejnenia",
    "platnosť do": "datum_platnosti_do", "dátum ukončenia": "datum_platnosti_do",
    "valid to": "datum_platnosti_do", "expiry date": "datum_platnosti_do",
    # Kategórie
    "kategória": "kategoria", "category": "kategoria",
    "druh": "kategoria", "type": "kategoria",
    "podkategória": "podkategoria", "subcategory": "podkategoria",
    "rok": "rok", "year": "rok",
    "stav": "stav", "status": "stav", "state": "stav",
}


def _enrich_with_details(page, docs: list[Dokument]) -> list[Dokument]:
    for i, doc in enumerate(docs):
        if not doc.url:
            continue
        try:
            print(f"  [→] Detail {i+1}/{len(docs)}: {doc.url}", file=sys.stderr)
            page.goto(doc.url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1200)
            _parse_detail_page(page, doc)
        except Exception as e:
            print(f"  [~] Detail: {e}", file=sys.stderr)
    return docs


def _parse_detail_page(page, doc: Dokument) -> None:
    _extract_label_values(page, doc)
    _extract_detail_fields(page, doc)
    _extract_files(page, doc)


def _extract_label_values(page, doc: Dokument) -> None:
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

    # div páry
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
            if any([doc.dodavatel, doc.suma, doc.datum]):
                break
    except Exception:
        pass


def _set_field(doc: Dokument, label: str, val: str) -> None:
    if not val:
        return
    fname = LABEL_MAP.get(label.strip())
    if fname and not getattr(doc, fname, ""):
        setattr(doc, fname, val)


def _extract_detail_fields(page, doc: Dokument) -> None:
    for sel, fname in [
        (".cislo, .contract-number, .document-number, [class*='number']", "cislo"),
        (".nazov, .subject, .predmet, [class*='subject'], [class*='title']", "nazov"),
        (".dodavatel, .supplier, .vendor, [class*='supplier']", "dodavatel"),
        (".ico, [class*='-ico']", "ico"),
        (".dic, [class*='-dic']", "dic"),
        (".suma, .amount, .price, .value, [class*='amount'], [class*='price']", "suma"),
        (".datum, .date, [class*='-date'], [class*='datum']", "datum"),
        (".datum-ucinnosti, .effective-date, [class*='effective']", "datum_ucinnosti"),
        (".datum-zverejnenia, .published-date, [class*='published']", "datum_zverejnenia"),
        (".kategoria, .category, [class*='category']", "kategoria"),
        (".oddelenie, .department, [class*='department']", "oddelenie"),
        (".stav, .status, [class*='status']", "stav"),
        (".rok, .year, [class*='year']", "rok"),
        (".popis, .description, [class*='description']", "popis"),
        (".poznamka, .note, .remark, [class*='note']", "poznamka"),
    ]:
        if getattr(doc, fname):
            continue
        try:
            el = page.locator(sel)
            if el.count() > 0:
                setattr(doc, fname, el.first.inner_text().strip())
        except Exception:
            pass


def _extract_files(page, doc: Dokument) -> None:
    try:
        seen = set(doc.subory)
        for sel in [
            "a[href$='.pdf']", "a[href$='.PDF']",
            "a[href*='download']", "a[href*='priloha']",
            "a[href*='attachment']", "a[href*='file']",
            ".attachment a", ".file-list a", ".download a",
            "[class*='attachment'] a", "[class*='file'] a",
            "[class*='download'] a", "[class*='priloha'] a",
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


# ---------------------------------------------------------------------------
# Navigačné pomocné funkcie
# ---------------------------------------------------------------------------

def _log_page_info(page) -> None:
    try:
        print(f"  [i] {page.title()} ({page.url})", file=sys.stderr)
    except Exception:
        pass


def _try_search(page, keyword: str) -> bool:
    for sel in [
        'input[type="search"]', 'input[placeholder*="hľadaj" i]',
        'input[placeholder*="vyhľadaj" i]', 'input[placeholder*="search" i]',
        'input[placeholder*="filter" i]', 'input[name="q"]', 'input[name="search"]',
        '.search-input input', '#search-input', '#keyword',
    ]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.clear()
                loc.first.fill(keyword)
                loc.first.press("Enter")
                print(f"  [✓] Search: '{keyword}' ({sel})", file=sys.stderr)
                return True
        except Exception:
            continue
    print("  [~] Search formulár nenájdený.", file=sys.stderr)
    return False


def _get_doc_types(doc_type: str) -> list[str]:
    if doc_type == "all":
        return ["zmluvy", "faktury", "objednavky"]
    return [doc_type] if doc_type in ("zmluvy", "faktury", "objednavky") else ["zmluvy", "faktury", "objednavky"]


def _navigate_to_section(page, section: str) -> None:
    labels = {
        "zmluvy": ["Zmluvy", "zmluvy", "Contracts"],
        "faktury": ["Faktúry", "faktury", "Faktury", "Invoices"],
        "objednavky": ["Objednávky", "objednavky", "Objednavky", "Orders"],
    }
    for label in labels.get(section, []):
        for tmpl in [
            f'a:text-is("{label}")', f'button:text-is("{label}")',
            f'[role="tab"]:text-is("{label}")', f'a:text("{label}")',
        ]:
            try:
                if page.locator(tmpl).count() > 0:
                    page.locator(tmpl).first.click()
                    return
            except Exception:
                continue


def _go_next_page(page) -> bool:
    for sel in [
        'a[aria-label="Next page"]', 'a[aria-label="Ďalej"]',
        'a:text-is("Ďalej")', 'a:text-is("»")', 'a:text-is(">")',
        ".pagination .next a", ".pagination li.next a", "[rel='next']",
        "a.page-next", ".next-page", 'button:text-is("Ďalej")',
        'button[aria-label="Next"]',
    ]:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_enabled():
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
        key = doc.url or f"{doc.typ}|{doc.cislo}|{doc.nazov}|{doc.dodavatel}"
        if key not in seen:
            seen.add(key)
            result.append(doc)
    return result


# ---------------------------------------------------------------------------
# Zobrazenie výsledkov
# ---------------------------------------------------------------------------

DOC_TYPE_SK = {"zmluvy": "Zmluvy", "faktury": "Faktúry", "objednavky": "Objednávky"}


def display_results(docs: list[Dokument], output_format: str = "table") -> None:
    if not docs:
        print("\nŽiadne výsledky nenájdené.")
        return

    if output_format == "json":
        def to_dict(d: Dokument) -> dict:
            r = asdict(d)
            r.pop("raw", None)
            return {k: v for k, v in r.items() if v or isinstance(v, list) and v}
        print(json.dumps([to_dict(d) for d in docs], ensure_ascii=False, indent=2))
        return

    if output_format == "csv":
        import csv, io
        fields = [
            "organizacia", "typ", "cislo", "nazov", "dodavatel", "ico", "dic",
            "suma", "suma_bez_dph", "mena",
            "datum", "datum_ucinnosti", "datum_zverejnenia", "datum_platnosti_do",
            "kategoria", "oddelenie", "stav", "rok",
            "objednavatel", "adresa_dodavatela", "popis", "poznamka", "url",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for d in docs:
            row = asdict(d)
            row["subory"] = " | ".join(row.get("subory", []))
            writer.writerow(row)
        print(buf.getvalue())
        return

    # Tabulkový formát
    W_ORG = 20
    W_TYP = 10
    W_CISLO = 16
    W_NAZOV = 36
    W_DODAVATEL = 26
    W_ICO = 12
    W_DATUM = 12
    W_SUMA = 15
    total_w = W_ORG + W_TYP + W_CISLO + W_NAZOV + W_DODAVATEL + W_ICO + W_DATUM + W_SUMA + 7

    print(f"\n{'='*total_w}")
    print(f"  Nájdených: {len(docs)} dokumentov – Spišská Nová Ves a organizácie")
    print(f"{'='*total_w}")
    print(
        f"{'Organizácia':<{W_ORG}} {'Typ':<{W_TYP}} {'Číslo':<{W_CISLO}} "
        f"{'Názov':<{W_NAZOV}} {'Dodávateľ':<{W_DODAVATEL}} "
        f"{'IČO':<{W_ICO}} {'Dátum':<{W_DATUM}} {'Suma':<{W_SUMA}}"
    )
    print("-" * total_w)

    by_org: dict[str, list[Dokument]] = {}
    for d in docs:
        by_org.setdefault(d.organizacia or d.org_slug, []).append(d)

    for org_name, org_docs in by_org.items():
        print(f"\n  === {org_name} ({len(org_docs)} dok.) ===")
        by_type: dict[str, list[Dokument]] = {}
        for d in org_docs:
            by_type.setdefault(d.typ, []).append(d)

        for dtype, type_docs in by_type.items():
            type_label = DOC_TYPE_SK.get(dtype, dtype)
            if len(by_type) > 1:
                print(f"  --- {type_label} ({len(type_docs)}) ---")
            for d in type_docs:
                org_short = (d.organizacia[:W_ORG-2] + "..") if len(d.organizacia) > W_ORG else d.organizacia
                cislo = (d.cislo[:W_CISLO-2] + "..") if len(d.cislo) > W_CISLO else d.cislo
                nazov = (d.nazov[:W_NAZOV-2] + "..") if len(d.nazov) > W_NAZOV else d.nazov
                dodavatel = (d.dodavatel[:W_DODAVATEL-2] + "..") if len(d.dodavatel) > W_DODAVATEL else d.dodavatel
                print(
                    f"{org_short:<{W_ORG}} {type_label:<{W_TYP}} {cislo:<{W_CISLO}} "
                    f"{nazov:<{W_NAZOV}} {dodavatel:<{W_DODAVATEL}} "
                    f"{d.ico:<{W_ICO}} {d.datum:<{W_DATUM}} {d.suma:<{W_SUMA}}"
                )
                extra = []
                if d.datum_ucinnosti:
                    extra.append(f"Účinnosť: {d.datum_ucinnosti}")
                if d.datum_zverejnenia:
                    extra.append(f"Zverejnené: {d.datum_zverejnenia}")
                if d.kategoria:
                    extra.append(f"Kat: {d.kategoria}")
                if d.oddelenie:
                    extra.append(f"Odd: {d.oddelenie}")
                if d.stav:
                    extra.append(f"Stav: {d.stav}")
                if d.suma_bez_dph:
                    extra.append(f"Bez DPH: {d.suma_bez_dph}")
                if extra:
                    indent = " " * (W_ORG + W_TYP + 2)
                    print(f"{indent}{' | '.join(extra)}")
                if d.url:
                    print(f"{' ' * (W_ORG + W_TYP + 2)}URL: {d.url}")
                for f in d.subory:
                    print(f"{' ' * (W_ORG + W_TYP + 2)}PDF: {f}")

    print(f"\n{'='*total_w}\n")


# ---------------------------------------------------------------------------
# Hlavný program
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="digitalnemesto_scraper",
        description="Scraper pre digitalnemesto.sk – Spišská Nová Ves a organizácie",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Príkladné príkazy:
  python digitalnemesto_scraper.py                          # všetky org SNV, všetky typy
  python digitalnemesto_scraper.py --org mesto              # iba Mesto SNV
  python digitalnemesto_scraper.py --org ts                 # iba Technické služby
  python digitalnemesto_scraper.py --keyword stavba         # filter kľúčovým slovom
  python digitalnemesto_scraper.py --typ zmluvy             # iba zmluvy
  python digitalnemesto_scraper.py --format json            # JSON výstup
  python digitalnemesto_scraper.py --format csv > data.csv  # CSV export
  python digitalnemesto_scraper.py --zoznam-org             # vypíše organizácie SNV
  python digitalnemesto_scraper.py --bez-detailov           # rýchlejšie, menej údajov
        """,
    )
    parser.add_argument(
        "--org", "-o",
        help=(
            "Slug alebo skratka organizácie (napr. mesto, ts, mks). "
            "Bez tohto parametra sa scrapujú VŠETKY organizácie SNV."
        ),
    )
    parser.add_argument("--keyword", "-k", help="Kľúčové slovo pre filter výsledkov")
    parser.add_argument(
        "--typ", "-t",
        choices=["zmluvy", "faktury", "objednavky", "all"],
        default="all",
        metavar="TYP",
        help="Typ dokumentov: zmluvy | faktury | objednavky | all (default: all)",
    )
    parser.add_argument(
        "--stranky", "-s",
        type=int, default=10, metavar="N",
        help="Max počet stránok na typ/org (default: 10)",
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
        help="Zobrazí okno prehliadača (pre debugging)",
    )
    parser.add_argument(
        "--bez-detailov",
        action="store_true",
        help="Preskočí načítanie detail stránok (rýchlejšie, menej údajov)",
    )

    args = parser.parse_args()

    if args.zoznam_org:
        print("\nOrganizácie Spišskej Novej Vsi na digitalnemesto.sk:")
        print(f"  {'Slug / skratka':<45} Názov")
        print("-" * 70)
        for slug, name in SNV_ORGANIZACIE.items():
            skratka = next((k for k, v in ORG_SKRATKY.items() if v == slug), "")
            display = f"{slug}" + (f" (--org {skratka})" if skratka else "")
            print(f"  {display:<45} {name}")
        print("\nTip: Ak vaša organizácia nie je v zozname, zadajte jej slug priamo.")
        print("     Napr. --org spiska-nova-ves-ts")
        return

    headless = not args.visible
    scrape_details = not args.bez_detailov
    keyword = args.keyword or ""
    doc_type = args.typ

    if args.org:
        # Preložíme skratku na slug ak treba
        org_slug = ORG_SKRATKY.get(args.org, args.org)
        # Ak to ešte nie je plný slug SNV, pridaj prefix
        if not org_slug.startswith("spiska-nova-ves") and org_slug not in SNV_ORGANIZACIE:
            org_slug = f"spiska-nova-ves-{org_slug}"
        org_nazov = SNV_ORGANIZACIE.get(org_slug, org_slug)

        print(
            f"[→] Organizácia: {org_nazov} | keyword: '{keyword}' | typ: {doc_type}",
            file=sys.stderr,
        )
        docs = scrape_organizacia(
            org_slug=org_slug,
            org_nazov=org_nazov,
            keyword=keyword,
            doc_type=doc_type,
            max_pages=args.stranky,
            headless=headless,
            scrape_details=scrape_details,
        )
    else:
        print(
            f"[→] Všetky organizácie SNV | keyword: '{keyword}' | typ: {doc_type}",
            file=sys.stderr,
        )
        docs = scrape_vsetky_organizacie(
            keyword=keyword,
            doc_type=doc_type,
            max_pages=args.stranky,
            headless=headless,
            scrape_details=scrape_details,
        )

    display_results(docs, output_format=args.format)


if __name__ == "__main__":
    main()
