# ⚡ NewsIQ — AI-Powered News Intelligence Platform

An end-to-end news dashboard that fetches real articles, processes them with Claude AI for **summaries**, **sentiment analysis**, and **key insights**, and presents everything in a polished responsive UI.

---

## 🏗️ Architecture

```
NewsData.io API  →  pipeline.py  →  SQLite DB  →  FastAPI  →  Browser Dashboard
                           ↕
                    Claude AI (Anthropic)
                    • 1-2 sentence summary
                    • Positive/negative/neutral sentiment
                    • 3-5 key insights
```

**Stack:** Python 3.10+ · FastAPI · SQLAlchemy · SQLite · Anthropic Claude · Vanilla HTML/JS

---

## ⚡ Quick Start (under 5 minutes)

### 1. Clone & enter
```bash
git clone <your-repo-url>
cd news-intelligence
```

### 2. Install Python dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 3. Set up environment variables
```bash
cp .env.example .env
# Edit .env and add your API keys:
#   NEWSDATA_API_KEY  — free at https://newsdata.io/
#   ANTHROPIC_API_KEY — at https://console.anthropic.com/
```

### 4. Start the server
```bash
cd ..   # back to project root
uvicorn backend.main:app --reload --port 8000
```

### 5. Open the dashboard
Visit **http://localhost:8000**

### 6. Run the pipeline
Click **"▶ Run Pipeline"** in the dashboard, or via CLI:
```bash
python -m backend.pipeline --query "artificial intelligence" --pages 10
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/articles` | List articles (search, filter, paginate) |
| GET | `/api/articles/{id}` | Full article with insights |
| GET | `/api/stats` | Dashboard statistics |
| POST | `/api/pipeline/run` | Trigger pipeline (background) |
| GET | `/api/pipeline/status` | Check pipeline progress |
| GET | `/docs` | Auto-generated Swagger UI |

### Query parameters for `/api/articles`
- `search` — full-text search in title/description
- `sentiment` — `positive` \| `negative` \| `neutral`
- `category` — filter by news category
- `sort_by` — `published_at` (default) or `sentiment_score`
- `page`, `limit` — pagination

---

## 🗄️ Database Schema

```sql
articles (
  article_id      TEXT PRIMARY KEY,
  title           TEXT NOT NULL,
  description     TEXT,
  content         TEXT,
  url             TEXT UNIQUE,
  image_url       TEXT,
  source_name     TEXT,
  category        TEXT,
  country         TEXT,
  language        TEXT,
  published_at    DATETIME,
  -- AI fields
  summary         TEXT,
  sentiment       TEXT,    -- positive | negative | neutral
  sentiment_score REAL,    -- -1.0 to +1.0
  key_insights    JSON,    -- array of 3-5 strings
  processed_at    DATETIME,
  created_at      DATETIME
)
```

---

## 🔄 Pipeline Details

1. **Fetch** — Paginates NewsData.io API (up to 500 articles per run)
2. **Clean** — Strips HTML tags, normalises whitespace, validates required fields
3. **Deduplicate** — Checks article_id and URL against existing DB records
4. **AI Process** — One Claude API call per new article returning JSON with summary, sentiment, and insights
5. **Store** — Bulk insert into SQLite

---

## 📁 Project Structure

```
news-intelligence/
├── backend/
│   ├── __init__.py
│   ├── main.py          # FastAPI app + routes
│   ├── database.py      # SQLAlchemy models
│   ├── pipeline.py      # Fetch → clean → deduplicate → AI → store
│   ├── ai_processor.py  # Claude AI integration
│   └── requirements.txt
├── frontend/
│   └── index.html       # Complete dashboard (no build step)
├── .env.example
└── README.md
```

---

## 🚀 Deployment (Optional)

### Railway (recommended — free tier)
```bash
# Install Railway CLI
npm install -g @railway/cli
railway login
railway init
railway up
```
Set environment variables in the Railway dashboard.

### Render / Fly.io
Any platform supporting Python 3.10+ and a persistent disk for SQLite works. For production, swap SQLite for PostgreSQL via `DATABASE_URL`.

---

## 🛠️ Tech Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Backend framework | FastAPI | Async, auto-docs, fast |
| Database | SQLite + SQLAlchemy | Zero setup for dev; swap to Postgres for prod |
| AI provider | Anthropic Claude | Best instruction-following; structured JSON output |
| News source | NewsData.io | Free tier, rich metadata, pagination |
| Frontend | Vanilla HTML/JS | No build step → instant setup; fully functional |

---

## 🔮 Future Improvements

- **Topic clustering** — Group articles by theme using embeddings
- **Trend graphs** — Sentiment over time per topic
- **Scheduled pipeline** — Cron job for hourly fresh data
- **Multi-language support** — Translate + analyse non-English articles
- **User bookmarks** — Save articles with personal notes
- **PostgreSQL** — For production scale