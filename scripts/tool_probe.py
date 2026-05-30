"""Read-only live probes for ACBUDDY external integrations.

Makes cheap, NON-MUTATING calls to confirm each integration is reachable and
authorized. No KB uploads, no GCS writes, no DEEP research runs.
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import requests

RESULTS = []


def record(name, status, detail):
    RESULTS.append((name, status, detail))
    print(f"[{status:^7}] {name}: {detail}")


def probe_openai():
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return record("OpenAI", "SKIP", "no OPENAI_API_KEY")
    try:
        r = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
        if r.status_code != 200:
            return record("OpenAI", "FAIL", f"HTTP {r.status_code}: {r.text[:120]}")
        ids = {m["id"] for m in r.json().get("data", [])}
        wanted = ["gpt-5.5", "gpt-5.4", "o4-mini"]
        present = {w: (w in ids) for w in wanted}
        record("OpenAI", "OK", f"auth ok, {len(ids)} models. configured: {present}")
    except Exception as e:
        record("OpenAI", "FAIL", f"{type(e).__name__}: {e}")


def probe_grok():
    key = os.getenv("GROK_API_KEY", "")
    if not key:
        return record("Grok", "SKIP", "no GROK_API_KEY")
    try:
        r = requests.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
        if r.status_code != 200:
            return record("Grok", "FAIL", f"HTTP {r.status_code}: {r.text[:160]}")
        ids = {m.get("id") for m in r.json().get("data", [])}
        configured = "grok-4-1-fast-reasoning"
        record("Grok", "OK", f"auth ok, models={sorted(ids)}; configured '{configured}' present={configured in ids}")
    except Exception as e:
        record("Grok", "FAIL", f"{type(e).__name__}: {e}")


def probe_newsapi():
    key = os.getenv("NEWSAPI_KEY", "")
    if not key:
        return record("NewsAPI", "SKIP", "no NEWSAPI_KEY")
    try:
        from app.services.news_client import search_news
        arts = search_news("artificial intelligence", key, days_back=7, max_results=3)
        if arts:
            record("NewsAPI", "OK", f"{len(arts)} articles; first='{arts[0]['title'][:60]}'")
        else:
            # Distinguish auth failure from empty: hit endpoint directly
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={"q": "test", "apiKey": key, "pageSize": 1},
                timeout=15,
            )
            record("NewsAPI", "FAIL" if r.status_code != 200 else "WARN",
                   f"client returned 0 articles; raw HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        record("NewsAPI", "FAIL", f"{type(e).__name__}: {e}")


def probe_financial():
    # Yahoo (no key) + SEC EDGAR (no key)
    try:
        from app.services.financial_client import get_stock_data, search_sec_filings
        q = get_stock_data("AAPL")
        if q.get("error"):
            record("Financial/Yahoo", "FAIL", f"{q.get('error')[:140]}")
        elif q.get("name"):
            record("Financial/Yahoo", "OK", f"AAPL name='{q['name']}' price={q.get('price')}")
        else:
            record("Financial/Yahoo", "WARN", f"no error but empty: {q}")
    except Exception as e:
        record("Financial/Yahoo", "FAIL", f"{type(e).__name__}: {e}")
    try:
        from app.services.financial_client import search_sec_filings
        f = search_sec_filings("Apple Inc", "10-K")
        if f and f[0].get("error"):
            record("Financial/EDGAR", "FAIL", f"{f[0]['error'][:140]}")
        elif f:
            record("Financial/EDGAR", "OK", f"{len(f)} hits; first={f[0]}")
        else:
            record("Financial/EDGAR", "WARN", "empty result list")
    except Exception as e:
        record("Financial/EDGAR", "FAIL", f"{type(e).__name__}: {e}")


def probe_elevenlabs():
    key = os.getenv("ELEVENLABS_API_KEY", "")
    if not key:
        return record("ElevenLabs", "SKIP", "no ELEVENLABS_API_KEY")
    try:
        r = requests.get(
            "https://api.elevenlabs.io/v1/convai/agents",
            headers={"xi-api-key": key},
            timeout=20,
        )
        if r.status_code != 200:
            return record("ElevenLabs", "FAIL", f"HTTP {r.status_code}: {r.text[:140]}")
        agents = r.json().get("agents", [])
        record("ElevenLabs", "OK", f"auth ok, {len(agents)} agents visible")
    except Exception as e:
        record("ElevenLabs", "FAIL", f"{type(e).__name__}: {e}")


def probe_gemini():
    key = os.getenv("GOOGLE_API_KEY", "")
    if not key:
        return record("Gemini", "SKIP", "no GOOGLE_API_KEY")
    try:
        from google import genai
        client = genai.Client(api_key=key)
        model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        resp = client.models.generate_content(model=model, contents="Reply with the single word OK.")
        txt = (resp.text or "").strip()
        record("Gemini/generate", "OK", f"model={model} replied='{txt[:40]}'")
    except Exception as e:
        record("Gemini/generate", "FAIL", f"{type(e).__name__}: {str(e)[:160]}")


def probe_gemini_search():
    key = os.getenv("GOOGLE_API_KEY", "")
    if not key:
        return record("Gemini/search-grounding", "SKIP", "no GOOGLE_API_KEY")
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        tool = types.Tool(google_search=types.GoogleSearch())
        resp = client.models.generate_content(
            model=model,
            contents="What is today's date approximately? One sentence.",
            config=types.GenerateContentConfig(tools=[tool]),
        )
        txt = (resp.text or "").strip()
        record("Gemini/search-grounding", "OK", f"replied='{txt[:80]}'")
    except Exception as e:
        record("Gemini/search-grounding", "FAIL", f"{type(e).__name__}: {str(e)[:160]}")


def probe_gcs():
    bucket = os.getenv("GCS_RESULTS_BUCKET", "")
    if not bucket:
        return record("GCS", "SKIP", "no GCS_RESULTS_BUCKET")
    try:
        from google.cloud import storage
        client = storage.Client()
        b = client.lookup_bucket(bucket)  # read-only; None if missing/no access
        if b is None:
            record("GCS", "WARN", f"bucket '{bucket}' not found or no access (auth/ADC?)")
        else:
            record("GCS", "OK", f"bucket '{bucket}' reachable, location={b.location}")
    except Exception as e:
        record("GCS", "FAIL", f"{type(e).__name__}: {str(e)[:160]}")


if __name__ == "__main__":
    print("=== ACBUDDY read-only integration probes ===\n")
    for fn in (probe_openai, probe_grok, probe_newsapi, probe_financial,
               probe_elevenlabs, probe_gemini, probe_gemini_search, probe_gcs):
        try:
            fn()
        except Exception as e:
            record(fn.__name__, "FAIL", f"probe crashed: {e}")
        time.sleep(0.3)
    print("\n=== SUMMARY ===")
    for name, status, _ in RESULTS:
        print(f"  {status:^7}  {name}")
