import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from report import generate_report
from scraper import (Book, PoliteFetcher, parse_books, parse_categories,
                     parse_next_page, parse_price, save)

LISTING = """
<div class="side_categories"><ul><li><a>Books</a><ul>
  <li><a href="catalogue/category/books/travel_2/index.html"> Travel </a></li>
  <li><a href="catalogue/category/books/poetry_23/index.html"> Poetry </a></li>
</ul></li></ul></div>
<article class="product_pod">
  <p class="star-rating Three"></p>
  <h3><a href="a-book_1/index.html" title="A Book">A Boo...</a></h3>
  <p class="price_color">Â£51.77</p>
  <p class="availability"> In stock </p>
</article>
<article class="product_pod">
  <p class="star-rating Five"></p>
  <h3><a href="b-book_2/index.html" title="B Book">B Boo...</a></h3>
  <p class="price_color">£10.00</p>
  <p class="availability"> Out of stock </p>
</article>
<article class="product_pod"><h3>broken item</h3></article>
<li class="next"><a href="page-2.html">next</a></li>
"""


def test_parse_price_handles_mojibake():
    assert parse_price("Â£51.77") == 51.77


def test_parse_books_extracts_fields_and_skips_malformed():
    books = parse_books(LISTING, "https://x.com/catalogue/page-1.html", "Travel")
    assert len(books) == 2
    assert books[0] == Book("A Book", "Travel", 51.77, 3, True,
                            "https://x.com/catalogue/a-book_1/index.html")
    assert books[1].rating == 5 and books[1].in_stock is False


def test_parse_categories_and_next_page():
    cats = parse_categories(LISTING, "https://x.com/")
    assert list(cats) == ["Travel", "Poetry"]
    assert parse_next_page(LISTING, "https://x.com/c/index.html") == "https://x.com/c/page-2.html"
    assert parse_next_page("<html></html>", "https://x.com/") is None


def _fetcher():
    return PoliteFetcher(delay=0, max_retries=3, respect_robots=False)


def test_retry_then_success():
    bad, good = MagicMock(status_code=503, headers={}), MagicMock(status_code=200, text="ok")
    good.raise_for_status = lambda: None
    f = _fetcher()
    with patch.object(f.session, "get", side_effect=[bad, good]), patch("scraper.time.sleep"):
        assert f.get("https://x.com") == "ok"


def test_gives_up_after_max_retries():
    f = _fetcher()
    with patch.object(f.session, "get", side_effect=requests.Timeout()) as g, \
         patch("scraper.time.sleep"):
        assert f.get("https://x.com") is None
        assert g.call_count == 3


def test_custom_headers_set():
    assert "EducationalScraper" in _fetcher().session.headers["User-Agent"]


def test_save_and_report(tmp_path):
    books = parse_books(LISTING, "https://x.com/", "Travel")
    save(books, tmp_path)
    assert (tmp_path / "books.csv").exists() and (tmp_path / "books.json").exists()
    text = generate_report(tmp_path / "books.csv", tmp_path / "summary_report.md")
    assert "Total books: **2**" in text
