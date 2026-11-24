# Automated Web Scraping & Data Extraction Pipeline

An ETL pipeline that scrapes the full book catalogue of [books.toscrape.com](https://books.toscrape.com)
(a sandbox site built for scraping practice), converts raw HTML into structured data, and
generates an analytical summary report.

## Features
| Requirement | Implementation |
|---|---|
| Target public dataset | Book listings (title, category, price, rating, stock, URL) across all categories |
| Rate limiting | Minimum delay between requests + random jitter (`--delay`, default 1s) |
| Custom headers | Descriptive `User-Agent`, `Accept`, `Accept-Language` on a persistent session |
| Retry logic | Exponential backoff on timeouts, connection errors and HTTP 429/5xx; honours `Retry-After` |
| Best practices | Checks `robots.txt`, handles 404s, skips malformed items instead of crashing |
| Parse & transform | BeautifulSoup -> typed `Book` dataclass -> `books.csv` and `books.json` |
| Summary report | `summary_report.md` generated automatically after every run (pandas) |

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage
```bash
python scraper.py                          # full run (~100 requests, a few minutes)
python scraper.py --max-categories 3 --max-pages 1   # quick test
python scraper.py --delay 2 -v             # slower and verbose
pytest                                      # run unit tests
```

## Output (`output/`)
- `books.csv` / `books.json` - extracted dataset
- `summary_report.md` - totals, price stats, rating distribution, top categories, extremes

## Project structure
```
scraper.py        # fetcher, parsers, pipeline, CLI
report.py         # summary statistics report
tests/            # parser, retry and report tests (no network needed)
requirements.txt
```

## Ethics
Only a site intended for scraping is targeted, requests are throttled, and robots.txt is respected.
