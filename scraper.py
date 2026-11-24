"""Automated Web Scraping & Data Extraction Pipeline (ETL).

Extract : polite HTTP fetching (rate limiting, custom headers, retries, robots.txt)
Transform: parse raw HTML into structured records
Load    : write CSV + JSON, then generate a summary statistics report
"""
import argparse
import csv
import json
import logging
import random
import re
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://books.toscrape.com/"
USER_AGENT = (
    "Mozilla/5.0 (compatible; EducationalScraper/1.0; "
    "+https://github.com/your-username/web-scraping-pipeline)"
)
RATING_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
RETRY_STATUSES = {429, 500, 502, 503, 504}

log = logging.getLogger("scraper")


@dataclass
class Book:
    title: str
    category: str
    price_gbp: float
    rating: int
    in_stock: bool
    url: str


# --------------------------------------------------------------------------- #
# EXTRACT: polite fetcher
# --------------------------------------------------------------------------- #
class PoliteFetcher:
    """requests.Session wrapper with rate limiting, headers, retries, robots.txt."""

    def __init__(self, base_url: str = BASE_URL, delay: float = 1.0,
                 max_retries: int = 4, timeout: float = 15.0,
                 respect_robots: bool = True):
        self.delay = delay
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.robots: Optional[RobotFileParser] = None
        if respect_robots:
            self.robots = RobotFileParser(urljoin(base_url, "/robots.txt"))
            try:
                self.robots.read()
            except Exception as exc:  # robots.txt unreachable -> proceed politely
                log.warning("Could not read robots.txt (%s); continuing", exc)
                self.robots = None

    def allowed(self, url: str) -> bool:
        return self.robots is None or self.robots.can_fetch(USER_AGENT, url)

    def _throttle(self) -> None:
        """Enforce a minimum gap between requests, plus a little random jitter."""
        wait = self.delay + random.uniform(0, self.delay * 0.25) - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def get(self, url: str) -> Optional[str]:
        """Return page HTML, or None if disallowed / failed after all retries."""
        if not self.allowed(url):
            log.warning("Blocked by robots.txt: %s", url)
            return None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 404:
                    log.warning("404 Not Found: %s", url)
                    return None
                if resp.status_code in RETRY_STATUSES:
                    retry_after = resp.headers.get("Retry-After", "")
                    backoff = float(retry_after) if retry_after.isdigit() else 2 ** attempt
                    log.warning("HTTP %s on %s (attempt %d/%d), retrying in %.1fs",
                                resp.status_code, url, attempt, self.max_retries, backoff)
                    time.sleep(backoff)
                    continue
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except (requests.ConnectionError, requests.Timeout) as exc:
                backoff = 2 ** attempt
                log.warning("%s on %s (attempt %d/%d), retrying in %ds",
                            type(exc).__name__, url, attempt, self.max_retries, backoff)
                time.sleep(backoff)
            except requests.HTTPError as exc:
                log.error("Non-retryable error for %s: %s", url, exc)
                return None
        log.error("Giving up on %s after %d attempts", url, self.max_retries)
        return None


# --------------------------------------------------------------------------- #
# TRANSFORM: HTML -> structured data
# --------------------------------------------------------------------------- #
def parse_categories(html: str, base_url: str = BASE_URL) -> dict:
    """Return {category_name: absolute_url} from the sidebar (skipping 'Books')."""
    soup = BeautifulSoup(html, "html.parser")
    cats = {}
    for a in soup.select("div.side_categories ul li ul li a"):
        cats[a.get_text(strip=True)] = urljoin(base_url, a["href"])
    return cats


def parse_price(text: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError(f"No price found in {text!r}")
    return float(match.group())


def parse_books(html: str, page_url: str, category: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    books = []
    for item in soup.select("article.product_pod"):
        try:
            link = item.select_one("h3 a")
            rating_cls = next((c for c in item.select_one("p.star-rating")["class"]
                               if c in RATING_MAP), None)
            books.append(Book(
                title=link["title"].strip(),
                category=category,
                price_gbp=parse_price(item.select_one("p.price_color").get_text()),
                rating=RATING_MAP.get(rating_cls, 0),
                in_stock="in stock" in item.select_one("p.availability").get_text().lower(),
                url=urljoin(page_url, link["href"]),
            ))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed item on %s: %s", page_url, exc)
    return books


def parse_next_page(html: str, page_url: str) -> Optional[str]:
    nxt = BeautifulSoup(html, "html.parser").select_one("li.next a")
    return urljoin(page_url, nxt["href"]) if nxt else None


# --------------------------------------------------------------------------- #
# PIPELINE
# --------------------------------------------------------------------------- #
def scrape_category(fetcher: PoliteFetcher, name: str, url: str,
                    max_pages: Optional[int] = None) -> Iterator[Book]:
    pages = 0
    while url and (max_pages is None or pages < max_pages):
        html = fetcher.get(url)
        if html is None:
            return
        found = parse_books(html, url, name)
        log.info("  %s: %d books from %s", name, len(found), url)
        yield from found
        url = parse_next_page(html, url)
        pages += 1


def run(output_dir: Path, delay: float, max_categories: Optional[int],
        max_pages: Optional[int], respect_robots: bool = True) -> list:
    fetcher = PoliteFetcher(delay=delay, respect_robots=respect_robots)
    home = fetcher.get(BASE_URL)
    if home is None:
        raise SystemExit("Could not load the home page; aborting.")
    categories = parse_categories(home)
    log.info("Found %d categories", len(categories))

    books = []
    for i, (name, url) in enumerate(categories.items()):
        if max_categories is not None and i >= max_categories:
            break
        log.info("[%d/%d] %s", i + 1, len(categories), name)
        books.extend(scrape_category(fetcher, name, url, max_pages))

    save(books, output_dir)
    return books


def save(books: list, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in fields(Book)]
    with open(output_dir / "books.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(asdict(b) for b in books)
    with open(output_dir / "books.json", "w", encoding="utf-8") as f:
        json.dump([asdict(b) for b in books], f, indent=2, ensure_ascii=False)
    log.info("Saved %d records to %s", len(books), output_dir)


def main() -> None:
    p = argparse.ArgumentParser(description="Books-to-Scrape ETL pipeline")
    p.add_argument("--output", type=Path, default=Path("output"))
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    p.add_argument("--max-categories", type=int, help="limit categories (for quick tests)")
    p.add_argument("--max-pages", type=int, help="limit pages per category")
    p.add_argument("--ignore-robots", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    books = run(args.output, args.delay, args.max_categories, args.max_pages,
                respect_robots=not args.ignore_robots)

    from report import generate_report  # automated summary report on every run
    generate_report(args.output / "books.csv", args.output / "summary_report.md")
    print(f"\nDone: {len(books)} books scraped -> {args.output}/")


if __name__ == "__main__":
    main()
