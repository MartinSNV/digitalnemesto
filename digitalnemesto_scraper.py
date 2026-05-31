#!/usr/bin/env python3
"""
Scraper pre digitalnemesto.sk
Vyhladava dokumenty samosprav (zmluvy, faktury, objednavky) podla mesta a klucoveho slova.

Pouzitie:
  python digitalnemesto_scraper.py --city presov --keyword stavba
  python digitalnemesto_scraper.py --city bratislava --keyword "IT sluzby" --typ zmluvy
  python digitalnemesto_scraper.py --city kosice --keyword servis --format json
  python digitalnemesto_scraper.py --zoznam-miest
"""

import argparse
import json
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Optional

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Nainštalujte playwright: pip install playwright && playwright install chromium", file=sys.stderr)
    sys.exit(1)


BASE_URL = "https://www.digitalnemesto.sk"

# Zname mesta na portali (slug -> zobrazovany nazov)
KNOWN_CITIES: dict[str, str] = {
    "bratislava": "Bratislava",
    "kosice": "Košice",
    "presov": "Prešov",
    "nitra": "Nitra",
    "zilina": "Žilina",
    "banska-bystrica": "Banská Bystrica",
    "trnava": "Trnava",
    "trencin": "Trenčín",
    "martin": "Martin",
    "poprad": "Poprad",
    "prievidza": "Prievidza",
    "zvolen": "Zvolen",
    "povazska-bystrica": "Považská Bystrica",
    "michalovce": "Michalovce",
    "nove-zamky": "Nové Zámky",
    "humenne": "Humenné",
    "spiska-nova-ves": "Spišská Nová Ves",
    "ruzomberok": "Ružomberok",
    "levice": "Levice",
    "piestany": "Piešťany",
    "komarno": "Komárno",
    "kosice-mestska-cast-stare-mesto": "Košice - Staré Mesto",
    "demo-mesto": "Demo Mesto",
}


@dataclass
class Dokument:
    nazov: str = ""
    dodavatel: str = ""
    datum: str = ""
    suma: str = ""
    typ: str = ""  # zmluva / faktura / objednavka
    url: str = ""
    popis: str = ""


def slugify(text: str) -> str:
    """Konvertuje nazov mesta na URL slug."""
    nfkd = unicodedata.normalize("NFKD", text.lower().strip())
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_str.replace(" ", "-")


def scrape_city(
    city_slug: str,
    keyword: str = "",
    doc_type: str = "all",
    max_pages: int = 10,
    headless: bool = True,
) -> list[Dokument]:
    """Scrape dokumenty z mesta na digitalnemesto.sk."""
    city_url = f"{BASE_URL}/mesto/{city_slug}/"
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
        page = context.new_page()

        try:
            print(f"[→] Načítavam: {city_url}", file=sys.stderr)
            response = page.goto(city_url, wait_until="domcontentloaded", timeout=30000)

            if response and response.status == 404:
                print(f"[!] Mesto '{city_slug}' neexistuje na {BASE_URL}", file=sys.stderr)
                print(f"    Tip: Skúste --zoznam-miest pre zoznam dostupných miest.", file=sys.stderr)
                return []

            if response and response.status == 403:
                print(f"[!] Prístup zamietnutý (403). Skúste --visible pre manuálne overenie.", file=sys.stderr)
                return []

            # Počkaj na dynamický obsah
            page.wait_for_timeout(3000)

            # Zisti strukturu stranky
            _log_page_info(page)

            # Skus pouzit vyhladavanie ak je k dispozicii
            searched = False
            if keyword:
                searched = _try_search(page, keyword)
                if searched:
                    page.wait_for_timeout(2000)

            # Nacitaj vsetky typy dokumentov
            types_to_scrape = _get_doc_types(doc_type)

            for dtype in types_to_scrape:
                # Skus navigovat na tab/sekciu pre dany typ
                _navigate_to_section(page, dtype)
                page.wait_for_timeout(1500)

                # Extrahuj dokumenty z vsetkych stranok
                page_num = 1
                while page_num <= max_pages:
                    page_docs = _extract_from_page(page, dtype)
                    docs.extend(page_docs)

                    if not page_docs:
                        break

                    if not _go_next_page(page):
                        break

                    page_num += 1
                    page.wait_for_timeout(1200)

        except PlaywrightTimeoutError:
            print("[!] Timeout - stránka sa nenačítala včas.", file=sys.stderr)
        except Exception as e:
            print(f"[!] Neočakávaná chyba: {e}", file=sys.stderr)
        finally:
            # Screenshot pre debugging
            if not headless:
                pass
            browser.close()

    # Klientsky filter podla klucoveho slova (fallback ak search nefungoval)
    if keyword:
        kw = keyword.lower()
        docs = [
            d for d in docs
            if kw in d.nazov.lower()
            or kw in d.dodavatel.lower()
            or kw in d.popis.lower()
        ]

    return docs


def _log_page_info(page) -> None:
    """Debug: Vypis info o aktualnej stranke."""
    try:
        title = page.title()
        url = page.url
        print(f"[i] Stránka: {title} ({url})", file=sys.stderr)
    except Exception:
        pass


def _try_search(page, keyword: str) -> bool:
    """Pokus o vyplnenie search formulara na stranke."""
    search_selectors = [
        'input[type="search"]',
        'input[placeholder*="hľadaj" i]',
        'input[placeholder*="vyhľadaj" i]',
        'input[placeholder*="search" i]',
        'input[placeholder*="filter" i]',
        'input[name="q"]',
        'input[name="search"]',
        'input[name="keyword"]',
        '.search-input input',
        '.filter-input',
        '#search-input',
        '#keyword',
    ]
    for selector in search_selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.clear()
                locator.first.fill(keyword)
                locator.first.press("Enter")
                print(f"[✓] Vyhľadávanie: '{keyword}' (selector: {selector})", file=sys.stderr)
                return True
        except Exception:
            continue

    # Pokus o button click po vyplneni
    for selector in search_selectors[:6]:
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.fill(keyword)
                # Hladaj submit tlacidlo
                btn_selectors = ['button[type="submit"]', 'button:text("Hľadaj")',
                                  'button:text("Vyhľadať")', '.search-btn', '.btn-search']
                for btn in btn_selectors:
                    if page.locator(btn).count() > 0:
                        page.locator(btn).first.click()
                        return True
        except Exception:
            continue

    print(f"[~] Search formulár nenájdený, filtrujem lokálne.", file=sys.stderr)
    return False


def _get_doc_types(doc_type: str) -> list[str]:
    """Vrati zoznam typov dokumentov na scrapovanie."""
    all_types = ["zmluvy", "faktury", "objednavky"]
    if doc_type == "all":
        return all_types
    mapping = {
        "zmluvy": ["zmluvy"],
        "faktury": ["faktury"],
        "objednavky": ["objednavky"],
    }
    return mapping.get(doc_type, all_types)


def _navigate_to_section(page, section: str) -> None:
    """Naviguj na tab/sekciu pre dany typ dokumentov."""
    labels = {
        "zmluvy": ["Zmluvy", "zmluvy", "Contracts"],
        "faktury": ["Faktúry", "faktury", "Faktury", "Invoices"],
        "objednavky": ["Objednávky", "objednavky", "Objednavky", "Orders"],
    }
    for label in labels.get(section, []):
        try:
            # Skus tab, link alebo tlacidlo
            for sel_template in [
                f'a:text-is("{label}")',
                f'button:text-is("{label}")',
                f'[role="tab"]:text-is("{label}")',
                f'li:text-is("{label}")',
                f'a:text("{label}")',
            ]:
                if page.locator(sel_template).count() > 0:
                    page.locator(sel_template).first.click()
                    return
        except Exception:
            continue


def _extract_from_page(page, doc_type: str) -> list[Dokument]:
    """Extrahuj dokumenty z aktualnej stranky - viac strategii."""
    docs: list[Dokument] = []

    # Strategia 1: HTML tabulky
    docs = _extract_from_tables(page, doc_type)
    if docs:
        return docs

    # Strategia 2: Zoznam (list items)
    docs = _extract_from_list(page, doc_type)
    if docs:
        return docs

    # Strategia 3: Karty (cards)
    docs = _extract_from_cards(page, doc_type)
    if docs:
        return docs

    return []


def _extract_from_tables(page, doc_type: str) -> list[Dokument]:
    """Extrakcia z HTML tabuliek."""
    docs: list[Dokument] = []
    try:
        tables = page.locator("table").all()
        for table in tables:
            headers = [th.inner_text().strip().lower() for th in table.locator("th").all()]
            rows = table.locator("tbody tr").all()

            for row in rows:
                cells = row.locator("td").all()
                if not cells:
                    continue

                doc = Dokument(typ=doc_type)
                cell_texts = [c.inner_text().strip() for c in cells]

                # Pokus o mapovanie stlpcov podla hlavicky
                for i, header in enumerate(headers):
                    if i >= len(cell_texts):
                        break
                    val = cell_texts[i]
                    if any(k in header for k in ["názov", "predmet", "name", "popis", "opis"]):
                        doc.nazov = val
                    elif any(k in header for k in ["dodávateľ", "firma", "partner", "company", "subjekt"]):
                        doc.dodavatel = val
                    elif any(k in header for k in ["dátum", "date", "datum"]):
                        doc.datum = val
                    elif any(k in header for k in ["suma", "cena", "hodnota", "amount", "price", "€"]):
                        doc.suma = val

                # Fallback: prvy stlpec = nazov, druhy = dodavatel, treti = datum, stvrty = suma
                if not doc.nazov and len(cell_texts) >= 1:
                    doc.nazov = cell_texts[0]
                if not doc.dodavatel and len(cell_texts) >= 2:
                    doc.dodavatel = cell_texts[1]
                if not doc.datum and len(cell_texts) >= 3:
                    doc.datum = cell_texts[2]
                if not doc.suma and len(cell_texts) >= 4:
                    doc.suma = cell_texts[3]

                # URL linky v riadku
                links = row.locator("a").all()
                if links:
                    try:
                        doc.url = links[0].get_attribute("href") or ""
                        if doc.url and not doc.url.startswith("http"):
                            doc.url = BASE_URL + doc.url
                    except Exception:
                        pass

                if doc.nazov:
                    docs.append(doc)
    except Exception as e:
        print(f"[~] Tabulka: {e}", file=sys.stderr)

    return docs


def _extract_from_list(page, doc_type: str) -> list[Dokument]:
    """Extrakcia z ul/li zoznamov."""
    docs: list[Dokument] = []
    try:
        item_selectors = [
            ".document-item", ".list-item", ".record-item",
            ".zmluva-item", ".faktura-item", ".objednavka-item",
            "[class*='document']", "[class*='record']",
            "li[class*='item']", ".result-item",
        ]
        for selector in item_selectors:
            items = page.locator(selector).all()
            if not items:
                continue
            for item in items:
                doc = Dokument(typ=doc_type)
                text = item.inner_text().strip()
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                if lines:
                    doc.nazov = lines[0]
                if len(lines) > 1:
                    doc.dodavatel = lines[1]
                if len(lines) > 2:
                    doc.datum = lines[2]
                if len(lines) > 3:
                    doc.suma = lines[3]
                try:
                    link = item.locator("a").first
                    href = link.get_attribute("href")
                    if href:
                        doc.url = href if href.startswith("http") else BASE_URL + href
                except Exception:
                    pass
                if doc.nazov:
                    docs.append(doc)
            if docs:
                break
    except Exception as e:
        print(f"[~] Zoznam: {e}", file=sys.stderr)
    return docs


def _extract_from_cards(page, doc_type: str) -> list[Dokument]:
    """Extrakcia z card-based layoutu."""
    docs: list[Dokument] = []
    try:
        card_selectors = [
            ".card", ".item-card", ".document-card",
            "[class*='card']", "article", ".tile",
        ]
        for selector in card_selectors:
            cards = page.locator(selector).all()
            if not cards:
                continue
            for card in cards:
                doc = Dokument(typ=doc_type)
                # Nazov - h nadpis v karte
                for heading in ["h1", "h2", "h3", "h4", ".title", ".name"]:
                    try:
                        el = card.locator(heading)
                        if el.count() > 0:
                            doc.nazov = el.first.inner_text().strip()
                            break
                    except Exception:
                        pass
                # Zvysny text
                full_text = card.inner_text().strip()
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                if not doc.nazov and lines:
                    doc.nazov = lines[0]
                # Link
                try:
                    href = card.locator("a").first.get_attribute("href")
                    if href:
                        doc.url = href if href.startswith("http") else BASE_URL + href
                except Exception:
                    pass
                if doc.nazov:
                    docs.append(doc)
            if docs:
                break
    except Exception as e:
        print(f"[~] Karty: {e}", file=sys.stderr)
    return docs


def _go_next_page(page) -> bool:
    """Naviguj na dalsiu stranku, vrati False ak nema."""
    next_selectors = [
        'a[aria-label="Next page"]',
        'a[aria-label="Ďalej"]',
        'a:text-is("Ďalej")',
        'a:text-is("»")',
        'a:text-is(">")',
        ".pagination .next a",
        ".pagination li.next a",
        "[rel='next']",
        "a.page-next",
        ".next-page",
    ]
    for selector in next_selectors:
        try:
            btn = page.locator(selector)
            if btn.count() > 0 and btn.first.is_enabled():
                btn.first.click()
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Zobrazenie vysledkov
# ---------------------------------------------------------------------------

DOC_TYPE_SK = {
    "zmluvy": "Zmluvy",
    "faktury": "Faktúry",
    "objednavky": "Objednávky",
}


def display_results(docs: list[Dokument], output_format: str = "table") -> None:
    if not docs:
        print("\nŽiadne výsledky nenájdené.")
        return

    if output_format == "json":
        print(json.dumps([asdict(d) for d in docs], ensure_ascii=False, indent=2))
        return

    if output_format == "csv":
        import csv, io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["typ", "nazov", "dodavatel", "datum", "suma", "url"])
        writer.writeheader()
        for d in docs:
            writer.writerow(asdict(d))
        print(buf.getvalue())
        return

    # Tabulkovy format
    W_TYP = 12
    W_NAZOV = 45
    W_DODAVATEL = 30
    W_DATUM = 12
    W_SUMA = 16
    total_w = W_TYP + W_NAZOV + W_DODAVATEL + W_DATUM + W_SUMA + 5

    print(f"\n{'='*total_w}")
    print(f"  Nájdených: {len(docs)} dokumentov")
    print(f"{'='*total_w}")
    print(
        f"{'Typ':<{W_TYP}} "
        f"{'Názov':<{W_NAZOV}} "
        f"{'Dodávateľ':<{W_DODAVATEL}} "
        f"{'Dátum':<{W_DATUM}} "
        f"{'Suma':<{W_SUMA}}"
    )
    print("-" * total_w)

    # Zoskup podla typu
    by_type: dict[str, list[Dokument]] = {}
    for d in docs:
        by_type.setdefault(d.typ, []).append(d)

    for dtype, type_docs in by_type.items():
        type_label = DOC_TYPE_SK.get(dtype, dtype.capitalize())
        if len(by_type) > 1:
            print(f"\n  --- {type_label} ({len(type_docs)}) ---")
        for d in type_docs:
            nazov = d.nazov[:W_NAZOV - 2] + ".." if len(d.nazov) > W_NAZOV else d.nazov
            dodavatel = d.dodavatel[:W_DODAVATEL - 2] + ".." if len(d.dodavatel) > W_DODAVATEL else d.dodavatel
            print(
                f"{type_label:<{W_TYP}} "
                f"{nazov:<{W_NAZOV}} "
                f"{dodavatel:<{W_DODAVATEL}} "
                f"{d.datum:<{W_DATUM}} "
                f"{d.suma:<{W_SUMA}}"
            )
            if d.url:
                print(f"{'':<{W_TYP}}   {d.url}")

    print(f"{'='*total_w}\n")


# ---------------------------------------------------------------------------
# Hlavny program
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="digitalnemesto_scraper",
        description="Scraper pre digitalnemesto.sk - zmluvy, faktury, objednavky samosprav",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Prikladne prikazy:
  python digitalnemesto_scraper.py --city presov --keyword stavba
  python digitalnemesto_scraper.py --city bratislava --keyword "IT sluzby" --typ zmluvy
  python digitalnemesto_scraper.py --city kosice --keyword servis --format json
  python digitalnemesto_scraper.py --city nitra --typ faktury --stranky 3
  python digitalnemesto_scraper.py --zoznam-miest
  python digitalnemesto_scraper.py --city presov --keyword audit --visible
        """,
    )
    parser.add_argument(
        "--city", "-c",
        help="Slug alebo nazov mesta (napr. presov, kosice, 'banska bystrica')"
    )
    parser.add_argument(
        "--keyword", "-k",
        help="Klucove slovo pre vyhladavanie"
    )
    parser.add_argument(
        "--typ", "-t",
        choices=["zmluvy", "faktury", "objednavky", "all"],
        default="all",
        metavar="TYP",
        help="Typ dokumentov: zmluvy | faktury | objednavky | all (default: all)",
    )
    parser.add_argument(
        "--stranky", "-s",
        type=int,
        default=10,
        metavar="N",
        help="Max pocet stranok na jeden typ dokumentov (default: 10)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["table", "json", "csv"],
        default="table",
        help="Format vystupu: table | json | csv (default: table)",
    )
    parser.add_argument(
        "--zoznam-miest",
        action="store_true",
        help="Zobrazi zoznam znamych miest (slugu)",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Zobrazi okno prehliadaca (uzitocne pre debugging)",
    )

    args = parser.parse_args()

    if args.zoznam_miest:
        print("\nZnáme mestá na digitalnemesto.sk:")
        print(f"  {'Slug (--city)':<45} Názov")
        print("-" * 65)
        for slug, name in sorted(KNOWN_CITIES.items()):
            print(f"  {slug:<45} {name}")
        print("\nTip: Ak vaše mesto nie je v zozname, skúste odhadnúť slug")
        print("     napr. 'banska-bystrica', 'stara-lubovna', ...")
        return

    if not args.city:
        parser.error("Zadajte --city (alebo --zoznam-miest pre zoznam dostupnych miest)")

    city_slug = slugify(args.city)
    headless = not args.visible

    print(
        f"[→] digitalnemesto.sk | mesto: {city_slug} "
        f"| keyword: '{args.keyword or ''}' "
        f"| typ: {args.typ}",
        file=sys.stderr,
    )

    docs = scrape_city(
        city_slug=city_slug,
        keyword=args.keyword or "",
        doc_type=args.typ,
        max_pages=args.stranky,
        headless=headless,
    )

    display_results(docs, output_format=args.format)


if __name__ == "__main__":
    main()
