# Film OV

Tutti gli spettacoli in versione originale nei cinema italiani (per ora Roma e Bologna), con link diretto alla prenotazione.

## How it works
Every night GitHub Actions (`.github/workflows/nightly.yml`):
1. tests the parser (`scraper/test_ov18tickets.py`)
2. reads the public 18tickets pages of each cinema, slowly (one page every 5 seconds)
3. stops if it finds fewer than 50 OV shows, so a broken run never replaces a good site
4. builds the site (`site/build_data.py` + `site/template.html`) into one `index.html`
5. saves the data in `data/` and publishes the site on GitHub Pages
6. opens an issue if a cinema that had OV shows now has none (GitHub emails you)

## Files
- `scraper/ov18tickets.py`: the 18tickets adapter. Cinemas are listed in `STOREFRONTS`.
- `site/build_data.py`: merges film titles (`ALIAS`), adds addresses (`VENUE`), builds the page.
- `data/ov_showtimes.csv`: last run, one row per OV screening.
- `data/run_stats.json`: shows per cinema, used to spot problems.

## Run by hand
Actions tab > "Aggiornamento notturno" > Run workflow.

## Run on your computer
    pip install -r requirements.txt
    python scraper/ov18tickets.py live --out data
    python site/build_data.py --out public
    open public/index.html
