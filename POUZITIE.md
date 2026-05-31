# Digitalnemesto.sk Scraper – Spišská Nová Ves

Scraper pre portál [digitalnemesto.sk](https://www.digitalnemesto.sk) zameraný na **Spišskú Novú Ves a jej organizácie**.
Zbiera všetky dostupné údaje o zmluvách, faktúrach a objednávkach.

## Inštalácia

```bash
pip install -r requirements.txt
playwright install chromium
```

## Použitie

### Základné príkazy

```bash
# Všetky organizácie SNV, všetky typy dokumentov
python digitalnemesto_scraper.py

# Iba mestský úrad SNV
python digitalnemesto_scraper.py --org mesto

# Iba Technické služby
python digitalnemesto_scraper.py --org ts

# Filter podľa kľúčového slova
python digitalnemesto_scraper.py --keyword stavba

# Iba zmluvy, JSON výstup
python digitalnemesto_scraper.py --typ zmluvy --format json

# CSV export všetkých faktúr
python digitalnemesto_scraper.py --typ faktury --format csv > faktury_snv.csv

# Zoznam organizácií SNV na portáli
python digitalnemesto_scraper.py --zoznam-org

# Rýchlejšie (bez návštevy detail stránok)
python digitalnemesto_scraper.py --bez-detailov

# Viditeľný prehliadač (debugging)
python digitalnemesto_scraper.py --org mesto --visible
```

## Parametre

| Parameter | Skratka | Popis | Default |
|-----------|---------|-------|---------|
| `--org` | `-o` | Slug alebo skratka organizácie SNV | _(všetky org SNV)_ |
| `--keyword` | `-k` | Kľúčové slovo pre filter | _(žiadny)_ |
| `--typ` | `-t` | `zmluvy` / `faktury` / `objednavky` / `all` | `all` |
| `--stranky` | `-s` | Max počet stránok na typ/org | `10` |
| `--format` | `-f` | `table` / `json` / `csv` | `table` |
| `--zoznam-org` | | Vypíš organizácie SNV | |
| `--visible` | | Zobraz okno prehliadača | _(headless)_ |
| `--bez-detailov` | | Preskočí detail stránky (rýchlejšie) | |

## Organizácie SNV

Spravuj zoznam v `SNV_ORGANIZACIE` v skripte. Skratky pre `--org`:

| Skratka | Slug | Organizácia |
|---------|------|-------------|
| `mesto` | `spiska-nova-ves` | Mesto Spišská Nová Ves |
| `mu` | `spiska-nova-ves-mestsky-urad` | Mestský úrad SNV |
| `ts` | `spiska-nova-ves-ts` | Technické služby |
| `mks` | `spiska-nova-ves-mks` | Mestské kultúrne stredisko |
| `mkc` | `spiska-nova-ves-mkc` | Mestské kultúrne centrum |
| `kniznica` | `spiska-nova-ves-kniznica` | Mestská knižnica |
| `bh` | `spiska-nova-ves-bh` | Bytové hospodárstvo |

Neznámy slug zadaj priamo: `--org spiska-nova-ves-nova-org`

## Zbierané dáta

Scraper získava **všetky dostupné polia** z každého dokumentu:

| Pole | Popis |
|------|-------|
| `organizacia` | Názov SNV organizácie |
| `typ` | zmluvy / faktury / objednavky |
| `cislo` | Číslo zmluvy / faktúry / objednávky |
| `nazov` | Predmet / názov dokumentu |
| `dodavatel` | Názov dodávateľa / zhotoviteľa |
| `ico` | IČO dodávateľa |
| `dic` | DIČ dodávateľa |
| `adresa_dodavatela` | Adresa dodávateľa |
| `objednavatel` | Objednávateľ / odberateľ |
| `oddelenie` | Oddelenie / referát mestského úradu |
| `suma` | Celková suma vrátane DPH |
| `suma_bez_dph` | Suma bez DPH |
| `mena` | Mena (EUR) |
| `datum` | Dátum podpisu / vystavenia |
| `datum_ucinnosti` | Dátum účinnosti / splatnosti |
| `datum_zverejnenia` | Dátum zverejnenia na portáli |
| `datum_platnosti_do` | Platnosť do |
| `kategoria` | Kategória dokumentu |
| `oddelenie` | Oddelenie / útvar |
| `rok` | Rok dokumentu |
| `stav` | Stav (aktívna, ukončená...) |
| `url` | URL detail stránky |
| `subory` | Linky na PDF prílohy |
| `poznamka` | Poznámka / doplňujúce info |

## Poznámky

- Web používa ochranu pred botmi – scraper používa headless Chromium s realistickými hlavičkami.
- Ak headless nefunguje, použite `--visible`.
- Scraper zachytáva aj API volania (JSON) – ak portál používa REST API, dáta sa načítajú priamo bez DOM parsingu.
- `--bez-detailov` preskočí návštevu detail stránok a je výrazne rýchlejší, ale niektoré polia (IČO, dátumy, PDF) môžu chýbať.
- Slugy organizácií je možné doplniť priamo do `SNV_ORGANIZACIE` v skripte.
