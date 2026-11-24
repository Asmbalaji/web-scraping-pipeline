"""Generate an analytical summary report (Markdown) from the scraped CSV."""
from datetime import datetime
from pathlib import Path

import pandas as pd


def generate_report(csv_path: Path, report_path: Path) -> str:
    df = pd.read_csv(csv_path)
    if df.empty:
        text = "# Scrape Summary Report\n\nNo records were scraped.\n"
        Path(report_path).write_text(text, encoding="utf-8")
        return text

    p = df["price_gbp"]
    lines = [
        "# Scrape Summary Report",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M:%S}_",
        "",
        "## Overview",
        f"- Total books: **{len(df)}**",
        f"- Categories: **{df['category'].nunique()}**",
        f"- In stock: **{df['in_stock'].mean():.1%}**",
        f"- Duplicate titles: **{df.duplicated('title').sum()}**",
        "",
        "## Price statistics (GBP)",
        f"- Mean: £{p.mean():.2f} | Median: £{p.median():.2f} | Std dev: £{p.std():.2f}",
        f"- Min: £{p.min():.2f} | Max: £{p.max():.2f}",
        "",
        "## Rating distribution",
        "| Stars | Books | Share |",
        "|---|---|---|",
    ]
    ratings = df["rating"].value_counts().sort_index()
    lines += [f"| {r} | {n} | {n / len(df):.1%} |" for r, n in ratings.items()]

    by_cat = (df.groupby("category")["price_gbp"]
                .agg(books="count", avg_price="mean")
                .sort_values("books", ascending=False))
    lines += ["", "## Top 10 categories by book count", "| Category | Books | Avg price |", "|---|---|---|"]
    lines += [f"| {c} | {int(r.books)} | £{r.avg_price:.2f} |" for c, r in by_cat.head(10).iterrows()]

    lines += ["", "## 5 most expensive books"]
    lines += [f"- {r.title} — £{r.price_gbp:.2f} ({r.category})"
              for r in df.nlargest(5, "price_gbp").itertuples()]
    lines += ["", "## 5 cheapest books"]
    lines += [f"- {r.title} — £{r.price_gbp:.2f} ({r.category})"
              for r in df.nsmallest(5, "price_gbp").itertuples()]

    text = "\n".join(lines) + "\n"
    Path(report_path).write_text(text, encoding="utf-8")
    return text
