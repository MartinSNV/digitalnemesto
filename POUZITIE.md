# Digitalnemesto.sk Scraper – Spišská Nová Ves

Scraper pre portál [digitalnemesto.sk](https://www.digitalnemesto.sk) zameraný na **Spišskú Novú Ves a jej organizácie**.
Zbiera všetky dostupné údaje o zmluvách, faktúrach a objednávkach.

## Štruktúra URL portálu

Portál je SPA s hash routingom:
```
https://www.digitalnemesto.sk/#/zverejnovanie/{city-slug}/{org-id}/{typ}/{rok}
```

Príklad:
```
https://www.digitalnemesto.sk/#/zverejnovanie/spisska-nova-ves/spisskanovaves/faktury-dodavatelske/2025
```

> **Poznámka:** Vyhľadávacie pole je viditeľné **iba na PC verzii** (desktop viewport ≥1024px).
> Scraper preto vždy používa viewport 1440×900, nie mobilný.

## Inštalácia

```bash
pip install -r requirements.txt
playwright install chromium
```

## Použitie

```bash
# Všetky organizácie SNV, všetky typy, posledné 3 roky
python digitalnemesto_scraper.py

# Iba Mesto SNV, aktuálny rok
python digitalnemesto_scraper.py --org mesto --rok 2025

# Technické služby, zmluvy 2024
python digitalnemesto_scraper.py --org ts --typ zmluvy --rok 2024

# Filter kľúčovým slovom
python digitalnemesto_scraper.py --keyword stavba

# JSON výstup so všetkými poliami
python digitalnemesto_scraper.py --format json

# CSV export faktúr za 2025
python digitalnemesto_scraper.py --typ faktury --rok 2025 --format csv > faktury_2025.csv

# Rýchlejšie (bez návštevy detail stránok)
python digitalnemesto_scraper.py --bez-detailov

# Viditeľný prehliadač (debugging)
python digitalnemesto_scraper.py --org mesto --visible

# Zoznam organizácií SNV
python digitalnemesto_scraper.py --zoznam-org
```

## Parametre

| Parameter | Skratka | Popis | Default |
|-----------|---------|-------|---------|
| `--org` | `-o` | Skratka alebo org-id organizácie | _(všetky org SNV)_ |
| `--keyword` | `-k` | Kľúčové slovo pre filter | _(žiadny)_ |
| `--typ` | `-t` | `zmluvy` / `faktury` / `faktury-odberatelske` / `objednavky` / `all` | `all` |
| `--rok` | `-r` | Rok dokumentov (napr. 2025) | _(posledné 3 roky)_ |
| `--stranky` | `-s` | Max počet stránok na typ/org/rok | `10` |
| `--format` | `-f` | `table` / `json` / `csv` | `table` |
| `--zoznam-org` | | Vypíš organizácie SNV | |
| `--visible` | | Zobraz okno prehliadača (desktop viewport) | |
| `--bez-detailov` | | Preskočí detail stránky – rýchlejšie, menej polí | |

## Organizácie SNV

| Skratka | org-id | Názov |
|---------|--------|-------|
| `mesto` | `spisskanovaves` | Mesto Spišská Nová Ves |
| `mu` | `muspiskanovaves` | Mestský úrad SNV |
| `ts` | `tsspiskanovaves` | Technické služby SNV |
| `mks` | `mksspiskanovaves` | Mestské kultúrne stredisko |
| `mkc` | `mksspn` | Mestské kultúrne centrum |
| `kniznica` | `kniznicaspiskanovaves` | Mestská knižnica |
| `bh` | `bhspiskanovaves` | Bytové hospodárstvo |
| `socialne` | `socialnecentrumspn` | Sociálne centrum |

> Ak org nie je v zozname, zadaj org-id priamo: `--org <org-id>`
> Napr. `--org tsspiskanovaves`

## Zbierané dáta

| Pole | Popis |
|------|-------|
| `organizacia` | Názov SNV organizácie |
| `rok` | Rok dokumentu |
| `typ` | zmluvy / faktury / faktury-odberatelske / objednavky |
| `cislo` | Číslo dokumentu |
| `nazov` | Predmet / názov |
| `dodavatel` | Dodávateľ / zhotoviteľ |
| `ico` | IČO dodávateľa |
| `dic` | DIČ dodávateľa |
| `adresa_dodavatela` | Adresa dodávateľa |
| `objednavatel` | Objednávateľ / odberateľ |
| `oddelenie` | Oddelenie / referát |
| `suma` | Celková suma s DPH |
| `suma_bez_dph` | Suma bez DPH |
| `mena` | Mena (EUR) |
| `datum` | Dátum podpisu / vystavenia |
| `datum_ucinnosti` | Dátum účinnosti / splatnosti |
| `datum_zverejnenia` | Dátum zverejnenia na portáli |
| `datum_platnosti_do` | Platnosť do |
| `kategoria` | Kategória dokumentu |
| `stav` | Stav dokumentu |
| `url` | URL detail stránky |
| `subory` | Linky na PDF prílohy |
| `poznamka` | Poznámka |

## Poznámky

- Portál blokuje boty – scraper používa headless Chromium s realistickými hlavičkami.
- **Search pole** je dostupné iba na PC viewporte (≥1024px) – scraper vždy používa 1440×900.
- Scraper zachytáva JSON API odpovede (portál je SPA) – ak API funguje, DOM parsing sa preskočí.
- `--bez-detailov` je výrazne rýchlejšie, ale niektoré polia (IČO, PDF prílohy, dátumy) môžu chýbať.
- **Org-id** v URL je zvyčajne názov organizácie bez diakritiky a medzier (napr. `tsspiskanovaves`).
  Správne org-id nájdeš v URL prehliadača pri prezeraní stránky organizácie.
