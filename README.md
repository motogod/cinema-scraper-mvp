# Cinema Scraper MVP

A starter backend for scraping Taiwan cinema showtimes, storing them in PostgreSQL, and exposing them to a React Native app through FastAPI.

## Stack

- FastAPI API server
- PostgreSQL
- SQLAlchemy 2.x
- Playwright for dynamic websites
- BeautifulSoup/lxml for parsing HTML
- Typer CLI for manual sync
- APScheduler for simple local scheduled sync

## Setup

```bash
cp .env.example .env
docker compose up -d
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
python scripts/init_db.py
```

## Run API

```bash
uvicorn app.main:app --reload
```

Open:

```txt
http://127.0.0.1:8000/docs
```

## Run scraper manually

```bash
python scripts/scrape.py vieshow
```

## Run local scheduler

```bash
python scripts/scheduler.py
```

## Notes

The Vie Show scraper is intentionally written as a practical MVP skeleton. Websites often change markup or load showtimes via internal APIs. The scraper therefore:

1. Uses Playwright so JavaScript-rendered content can be captured.
2. Saves a debug HTML file to `debug/vieshow-showtimes.html`.
3. Attempts to parse movie/showtime blocks with conservative heuristics.
4. Keeps source fields and `scraped_at` for debugging.

When you confirm the exact DOM structure/API payload of each cinema, update `app/scrapers/vieshow.py` selectors and parsing logic.
