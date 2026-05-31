# Digitalnemesto.sk Scraper

Scraper pre portál [digitalnemesto.sk](https://www.digitalnemesto.sk) – zverejňovanie zmlúv, faktúr a objednávok slovenských samospráv.

## Inštalácia

```bash
cd scraper
pip install -r requirements.txt
playwright install chromium
```

## Použitie

### Základné vyhľadávanie

```bash
# Vyhľadaj zmluvy v Prešove obsahujúce slovo 'stavba'
python digitalnemesto_scraper.py --city presov --keyword stavba

# Vyhľadaj IT zmluvy v Bratislave
python digitalnemesto_scraper.py --city bratislava --keyword "IT služby" --typ zmluvy

# Všetky faktúry v Košiciach
python digitalnemesto_scraper.py --city kosice --typ faktury

# Výstup v JSON formáte
python digitalnemesto_scraper.py --city nitra --keyword servis --format json

# CSV export
python digitalnemesto_scraper.py --city zilina --typ objednavky --format csv > vystup.csv
```

### Ďalšie možnosti

```bash
# Zoznam dostupných miest
python digitalnemesto_scraper.py --zoznam-miest

# Viditeľný prehliadač (pre debugging / ak nefunguje headless)
python digitalnemesto_scraper.py --city presov --keyword audit --visible

# Max 3 stránky výsledkov
python digitalnemesto_scraper.py --city bratislava --keyword stavba --stranky 3
```

## Parametre

| Parameter | Skratka | Popis | Default |
|-----------|---------|-------|---------|
| `--city` | `-c` | Slug alebo názov mesta | povinný |
| `--keyword` | `-k` | Kľúčové slovo pre filter | _(žiadny)_ |
| `--typ` | `-t` | `zmluvy` / `faktury` / `objednavky` / `all` | `all` |
| `--stranky` | `-s` | Max počet stránok | `10` |
| `--format` | `-f` | `table` / `json` / `csv` | `table` |
| `--visible` | | Zobraz okno prehliadača | _(headless)_ |
| `--zoznam-miest` | | Vypíš dostupné mestá | |

## Výstup (table formát)

```
==============================================================================
  Nájdených: 12 dokumentov
==============================================================================
Typ          Názov                                         Dodávateľ                       Dátum        Suma
------------------------------------------------------------------------------
  --- Zmluvy (8) ---
Zmluvy       Zmluva o dielo - Rekonštrukcia chodníka...   ABC Stavby s.r.o.               2024-03-15   45 000,00 €
             https://www.digitalnemesto.sk/mesto/presov/...
...
```

## Poznámky

- Web používa ochranu pred botmi (Cloudflare) – scraper používa headless Chromium.
- Ak headless nefunguje, skúste `--visible` pre overenie v reálnom prehliadači.
- Ak mesto nie je v zozname, odhadnite slug (diakritiku bez, medzery ako `-`):
  - `Banská Bystrica` → `banska-bystrica`
  - `Stará Ľubovňa` → `stara-lubovna`
- Scraper filtruje výsledky klientsky ako fallback, ak serverové vyhľadávanie nefunguje.
