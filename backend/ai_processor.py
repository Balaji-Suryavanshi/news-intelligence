"""
ai_processor.py — Gemini-powered summarization, sentiment & insight extraction
One API call per article returns all three in structured JSON.
"""

import os
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# We will get the API key in the function to ensure it's loaded from .env if updated
def get_gemini_url():
    api_key = os.getenv("GEMINI_API_KEY")
    return f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a professional news analyst. 
Analyze the provided article and respond ONLY with a valid JSON object.
No markdown fences, no extra text — pure JSON."""

ANALYSIS_PROMPT = """Analyze this news article and return a JSON object with exactly these keys:

{{
  "summary": "<1-2 sentence summary capturing the main event and its significance>",
  "sentiment": "<one of: positive | negative | neutral>",
  "sentiment_score": <float between -1.0 (very negative) and 1.0 (very positive)>,
  "key_insights": [
    "<insight 1>",
    "<insight 2>",
    "<insight 3>"
  ]
}}

Rules:
- summary: factual, concise, no opinion
- sentiment_score: 0.0 = neutral, match the 'sentiment' label
- key_insights: 3-5 items, each a single sentence, start with a verb

Article:
---
Title: {title}
Description: {description}
Content: {content}
---"""


def _truncate(text: Optional[str], limit: int = 1200) -> str:
    if not text:
        return ""
    return text[:limit]


def process_article(title: str,
                    description: Optional[str],
                    content: Optional[str]) -> dict:
    """
    Call Gemini to analyse a single article.

    Returns:
        {
          "summary": str,
          "sentiment": "positive|negative|neutral",
          "sentiment_score": float,
          "key_insights": list[str]
        }
    Raises RuntimeError on failure so callers can skip gracefully.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in environment")

    prompt = ANALYSIS_PROMPT.format(
        title=title or "(no title)",
        description=_truncate(description, 400),
        content=_truncate(content, 1200),
    )

    full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"

    payload = {
        "contents": [{
            "parts": [{
                "text": full_prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }

    url = get_gemini_url()

    try:
        response = httpx.post(url, json=payload, timeout=30.0)
        
        if response.status_code != 200:
            raise RuntimeError(f"Gemini API returned status {response.status_code}: {response.text}")
            
        data = response.json()
        
        # Extract text from response
        try:
            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Failed to parse Gemini response structure: {e}")

        # Strip accidental markdown fences if any
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)

        # ── Validation & fallback defaults ────────────────────────────
        allowed_sentiments = {"positive", "negative", "neutral"}
        if result.get("sentiment") not in allowed_sentiments:
            result["sentiment"] = "neutral"

        score = float(result.get("sentiment_score", 0.0))
        result["sentiment_score"] = max(-1.0, min(1.0, score))

        if not isinstance(result.get("key_insights"), list):
            result["key_insights"] = []

        result["key_insights"] = result["key_insights"][:5]   # cap at 5

        return result

    except json.JSONDecodeError as exc:
        logger.error("JSON parse error for article '%s': %s", title[:60], exc)
        raise RuntimeError(f"AI response was not valid JSON: {exc}") from exc
    except httpx.HTTPError as exc:
        logger.error("HTTP error calling Gemini: %s", exc)
        raise RuntimeError(f"Gemini API error: {exc}") from exc


def batch_process(articles: list[dict]) -> list[dict]:
    """
    Process a list of article dicts.
    Each dict must have: title, description, content.
    Returns the same list with ai_ fields injected; failed items get None values.
    """
    results = []
    for i, art in enumerate(articles, 1):
        logger.info("AI processing %d/%d: %s", i, len(articles), art["title"][:60])
        try:
            ai = process_article(art["title"], art.get("description"), art.get("content"))
            art.update({
                "summary":         ai["summary"],
                "sentiment":       ai["sentiment"],
                "sentiment_score": ai["sentiment_score"],
                "key_insights":    ai["key_insights"],
            })
        except RuntimeError as exc:
            logger.warning("Skipping AI for article '%s': %s", art["title"][:60], exc)
            art.update({
                "summary":         None,
                "sentiment":       "neutral",
                "sentiment_score": 0.0,
                "key_insights":    [],
            })
        results.append(art)
    return results