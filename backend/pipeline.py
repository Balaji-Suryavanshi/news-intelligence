"""
pipeline.py — NewsData.io fetcher → cleaner → deduplicator → DB writer
Usage:
    python -m backend.pipeline                  # fetch 'technology' news
    python -m backend.pipeline --query "AI" --pages 5
"""

import os
import re
import logging
import hashlib
import argparse
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv()

from .database import SessionLocal, Article, init_db
from .ai_processor import process_article

logger = logging.getLogger(__name__)

NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY", "")
NEWSDATA_BASE    = "https://newsdata.io/api/1/news"


# ════════════════════════════════════════════════════════════════════════════
# 1.  FETCH
# ════════════════════════════════════════════════════════════════════════════

def fetch_page(query: str, page_token: Optional[str] = None) -> dict:
    """
    Fetch one page (up to 10 articles) from NewsData.io.
    Returns the raw JSON response dict.
    """
    params = {
        "apikey":   NEWSDATA_API_KEY,
        "q":        query,
        "language": "en",
    }
    if page_token:
        params["page"] = page_token

    try:
        resp = httpx.get(NEWSDATA_BASE, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("HTTP %s fetching page: %s", exc.response.status_code, exc)
        raise
    except httpx.RequestError as exc:
        logger.error("Network error fetching page: %s", exc)
        raise


def fetch_articles(query: str = "technology", max_pages: int = 10) -> list[dict]:
    """
    Paginate through NewsData.io and collect raw article dicts.
    Stops after `max_pages` or when there are no more results.
    """
    all_raw   = []
    page_token = None

    for page_num in range(1, max_pages + 1):
        logger.info("Fetching page %d (query='%s') …", page_num, query)
        try:
            data = fetch_page(query, page_token)
        except Exception:
            logger.warning("Failed on page %d; stopping fetch.", page_num)
            break

        results = data.get("results") or []
        if not results:
            logger.info("No results on page %d; done.", page_num)
            break

        all_raw.extend(results)
        logger.info("  → got %d articles (total so far: %d)", len(results), len(all_raw))

        page_token = data.get("nextPage")
        if not page_token:
            break

    return all_raw


# ════════════════════════════════════════════════════════════════════════════
# 2.  CLEAN
# ════════════════════════════════════════════════════════════════════════════

_HTML_TAG  = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _clean_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = _HTML_TAG.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text or None


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def clean_article(raw: dict) -> Optional[dict]:
    """
    Validate + clean one raw NewsData result.
    Returns None if the article is unfit to store (no title/url).
    """
    title = _clean_text(raw.get("title"))
    url   = raw.get("link") or raw.get("url")

    if not title or not url:
        return None

    # Stable ID: sha256 of URL so re-runs are idempotent
    article_id = raw.get("article_id") or hashlib.sha256(url.encode()).hexdigest()[:24]

    categories = raw.get("category") or []
    category   = categories[0] if categories else None

    countries  = raw.get("country") or []
    country    = countries[0] if countries else None

    return {
        "article_id":   article_id,
        "title":        title,
        "description":  _clean_text(raw.get("description")),
        "content":      _clean_text(raw.get("content")),
        "url":          url,
        "image_url":    raw.get("image_url"),
        "source_name":  raw.get("source_id") or raw.get("source_name"),
        "category":     category,
        "country":      country,
        "language":     raw.get("language"),
        "published_at": _parse_date(raw.get("pubDate")),
    }


# ════════════════════════════════════════════════════════════════════════════
# 3.  DEDUPLICATE
# ════════════════════════════════════════════════════════════════════════════

def deduplicate(articles: list[dict], db: Session) -> list[dict]:
    """Return only articles not already in the database (by article_id or URL)."""
    existing_ids  = {r[0] for r in db.query(Article.article_id).all()}
    existing_urls = {r[0] for r in db.query(Article.url).all()}

    seen_ids_this_batch: set[str] = set()
    unique = []
    for art in articles:
        aid = art["article_id"]
        if aid in existing_ids or art["url"] in existing_urls:
            continue
        if aid in seen_ids_this_batch:
            continue
        seen_ids_this_batch.add(aid)
        unique.append(art)

    logger.info("Dedup: %d new out of %d cleaned", len(unique), len(articles))
    return unique


# ════════════════════════════════════════════════════════════════════════════
# 4.  STORE
# ════════════════════════════════════════════════════════════════════════════

def save_articles(articles: list[dict], db: Session) -> int:
    """Bulk-insert processed articles. Returns count saved."""
    saved = 0
    for art in articles:
        obj = Article(
            article_id      = art["article_id"],
            title           = art["title"],
            description     = art.get("description"),
            content         = art.get("content"),
            url             = art["url"],
            image_url       = art.get("image_url"),
            source_name     = art.get("source_name"),
            category        = art.get("category"),
            country         = art.get("country"),
            language        = art.get("language"),
            published_at    = art.get("published_at"),
            summary         = art.get("summary"),
            sentiment       = art.get("sentiment", "neutral"),
            sentiment_score = art.get("sentiment_score", 0.0),
            key_insights    = art.get("key_insights", []),
            processed_at    = datetime.utcnow() if art.get("summary") else None,
        )
        db.add(obj)
        saved += 1
    db.commit()
    return saved


# ════════════════════════════════════════════════════════════════════════════
# 5.  FULL PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def run_pipeline(query: str = "technology", max_pages: int = 10) -> dict:
    """
    End-to-end pipeline:
      fetch → clean → deduplicate → AI process → save

    Returns a summary dict with counts.
    """
    init_db()
    db = SessionLocal()

    try:
        # Step 1: Fetch
        raw_articles = fetch_articles(query, max_pages)
        logger.info("Fetched %d raw articles", len(raw_articles))

        # Step 2: Clean
        cleaned = [c for r in raw_articles if (c := clean_article(r)) is not None]
        logger.info("Cleaned: %d valid articles", len(cleaned))

        # Step 3: Deduplicate
        new_articles = deduplicate(cleaned, db)
        if not new_articles:
            logger.info("No new articles to process.")
            return {"fetched": len(raw_articles), "cleaned": len(cleaned), "new": 0, "saved": 0}

        # Step 4: AI process (one call per article)
        logger.info("Running AI processing on %d articles …", len(new_articles))
        for i, art in enumerate(new_articles, 1):
            logger.info("  [%d/%d] %s", i, len(new_articles), art["title"][:70])
            try:
                ai = process_article(art["title"], art.get("description"), art.get("content"))
                art.update(ai)
            except Exception as exc:
                logger.warning("AI failed for '%s': %s", art["title"][:60], exc)
                art.setdefault("summary", None)
                art.setdefault("sentiment", "neutral")
                art.setdefault("sentiment_score", 0.0)
                art.setdefault("key_insights", [])

        # Step 5: Save
        saved = save_articles(new_articles, db)
        logger.info("Pipeline complete. Saved %d articles.", saved)

        return {
            "fetched": len(raw_articles),
            "cleaned": len(cleaned),
            "new":     len(new_articles),
            "saved":   saved,
        }
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Run the news pipeline")
    parser.add_argument("--query", default="technology", help="Search query")
    parser.add_argument("--pages", type=int, default=10, help="Max pages to fetch")
    args = parser.parse_args()

    summary = run_pipeline(args.query, args.pages)
    print("\n✅ Pipeline summary:", summary)