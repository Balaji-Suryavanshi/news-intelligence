"""
main.py — FastAPI application
Endpoints:
  GET  /api/articles          — list with search, filter, pagination
  GET  /api/articles/{id}     — single article detail
  GET  /api/stats             — dashboard statistics
  POST /api/pipeline/run      — trigger pipeline (async background task)
  GET  /api/pipeline/status   — last pipeline run status
"""

import os
import logging
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import func, desc, or_
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .database import get_db, init_db, Article

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI News Intelligence API",
    description="Fetch, process, and surface news insights powered by Claude AI",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track latest pipeline run (in-memory; fine for this scope)
pipeline_status: dict = {"running": False, "last_run": None, "last_result": None}


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("Database initialised.")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ArticleSummary(BaseModel):
    article_id:      str
    title:           str
    description:     Optional[str]
    url:             str
    image_url:       Optional[str]
    source_name:     Optional[str]
    category:        Optional[str]
    published_at:    Optional[datetime]
    sentiment:       Optional[str]
    sentiment_score: Optional[float]
    summary:         Optional[str]

    class Config:
        from_attributes = True


class ArticleDetail(ArticleSummary):
    content:      Optional[str]
    key_insights: Optional[list]
    processed_at: Optional[datetime]


class StatsResponse(BaseModel):
    total_articles:    int
    processed_count:   int
    positive_count:    int
    negative_count:    int
    neutral_count:     int
    sources_count:     int
    categories:        list[dict]


class PipelineRequest(BaseModel):
    query:     str = "technology"
    max_pages: int = 10


# ── Helper ────────────────────────────────────────────────────────────────────

def _run_pipeline_task(query: str, max_pages: int):
    """Background task wrapper."""
    pipeline_status["running"] = True
    try:
        from .pipeline import run_pipeline
        result = run_pipeline(query, max_pages)
        pipeline_status["last_result"] = result
        pipeline_status["last_run"]    = datetime.utcnow().isoformat()
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        pipeline_status["last_result"] = {"error": str(exc)}
    finally:
        pipeline_status["running"] = False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/articles", response_model=dict)
def list_articles(
    search:    Optional[str] = Query(None, description="Search in title/description"),
    sentiment: Optional[str] = Query(None, description="positive|negative|neutral"),
    category:  Optional[str] = Query(None),
    source:    Optional[str] = Query(None),
    sort_by:   str           = Query("published_at", description="published_at|sentiment_score"),
    page:      int           = Query(1, ge=1),
    limit:     int           = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(Article)

    if search:
        term = f"%{search}%"
        q = q.filter(or_(Article.title.ilike(term), Article.description.ilike(term)))
    if sentiment:
        q = q.filter(Article.sentiment == sentiment)
    if category:
        q = q.filter(Article.category == category)
    if source:
        q = q.filter(Article.source_name == source)

    total = q.count()

    if sort_by == "sentiment_score":
        q = q.order_by(desc(Article.sentiment_score))
    else:
        q = q.order_by(desc(Article.published_at))

    articles = q.offset((page - 1) * limit).limit(limit).all()

    return {
        "total":    total,
        "page":     page,
        "limit":    limit,
        "pages":    (total + limit - 1) // limit,
        "articles": [ArticleSummary.from_orm(a).dict() for a in articles],
    }


@app.get("/api/articles/{article_id}", response_model=ArticleDetail)
def get_article(article_id: str, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.article_id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleDetail.from_orm(article)


@app.get("/api/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    total      = db.query(func.count(Article.article_id)).scalar()
    processed  = db.query(func.count(Article.article_id)).filter(Article.summary.isnot(None)).scalar()
    positive   = db.query(func.count(Article.article_id)).filter(Article.sentiment == "positive").scalar()
    negative   = db.query(func.count(Article.article_id)).filter(Article.sentiment == "negative").scalar()
    neutral    = db.query(func.count(Article.article_id)).filter(Article.sentiment == "neutral").scalar()
    sources    = db.query(func.count(func.distinct(Article.source_name))).scalar()

    # Top categories
    cat_rows = (
        db.query(Article.category, func.count(Article.article_id).label("count"))
        .filter(Article.category.isnot(None))
        .group_by(Article.category)
        .order_by(desc("count"))
        .limit(8)
        .all()
    )
    categories = [{"name": r[0], "count": r[1]} for r in cat_rows]

    return StatsResponse(
        total_articles  = total,
        processed_count = processed,
        positive_count  = positive,
        negative_count  = negative,
        neutral_count   = neutral,
        sources_count   = sources,
        categories      = categories,
    )


@app.post("/api/pipeline/run")
def trigger_pipeline(req: PipelineRequest, background_tasks: BackgroundTasks):
    if pipeline_status["running"]:
        return {"message": "Pipeline already running", "status": pipeline_status}
    background_tasks.add_task(_run_pipeline_task, req.query, req.max_pages)
    return {"message": "Pipeline started", "query": req.query, "max_pages": req.max_pages}


@app.get("/api/pipeline/status")
def get_pipeline_status():
    return pipeline_status


# ── Serve frontend ────────────────────────────────────────────────────────────

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def serve_frontend():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))