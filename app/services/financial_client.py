"""Financial data tools — stock data via Alpha Vantage / Yahoo Finance, SEC filings via EDGAR."""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

_YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
_YAHOO_COOKIE_URL = "https://fc.yahoo.com/"
_YAHOO_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
_EDGAR_BASE = "https://efts.sec.gov/LATEST/search-index"
_ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"

# Yahoo's v7 quote endpoint requires a cookie + matching "crumb" token (a bare
# request returns 401). The browser-like UA matters — Yahoo rejects the default
# requests/library UA. The session + crumb are cached and reused across calls,
# and refreshed on demand (e.g. after a 401 from an expired crumb).
_YAHOO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_yahoo_lock = threading.Lock()
_yahoo_session: requests.Session | None = None
_yahoo_crumb: str = ""
_yahoo_crumb_ts: float = 0.0
_YAHOO_CRUMB_TTL_S = 1800.0  # refresh the handshake at most every ~30 min


def get_stock_data(ticker: str, api_key: str = "") -> dict:
    """Get stock overview and recent price data.

    Uses Alpha Vantage if API key is provided, otherwise falls back to Yahoo Finance.
    Returns dict with: name, price, change, market_cap, pe_ratio, description.
    """
    if api_key:
        return _alpha_vantage_overview(ticker, api_key)
    return _yahoo_quote(ticker)


def _alpha_vantage_overview(ticker: str, api_key: str) -> dict:
    """Fetch company overview from Alpha Vantage."""
    try:
        resp = requests.get(
            _ALPHA_VANTAGE_BASE,
            params={"function": "OVERVIEW", "symbol": ticker, "apikey": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if "Symbol" not in data:
            return {"error": f"No data for ticker {ticker}", "raw": str(data)[:200]}
        return {
            "ticker": data.get("Symbol", ticker),
            "name": data.get("Name", ""),
            "description": data.get("Description", "")[:500],
            "market_cap": data.get("MarketCapitalization", ""),
            "pe_ratio": data.get("PERatio", ""),
            "eps": data.get("EPS", ""),
            "dividend_yield": data.get("DividendYield", ""),
            "52_week_high": data.get("52WeekHigh", ""),
            "52_week_low": data.get("52WeekLow", ""),
            "sector": data.get("Sector", ""),
            "industry": data.get("Industry", ""),
        }
    except Exception as e:
        logger.warning("Alpha Vantage failed for %s: %s", ticker, e)
        return {"error": str(e)}


def _yahoo_handshake(force: bool = False) -> tuple[requests.Session | None, str]:
    """Return a (session, crumb) pair authenticated against Yahoo Finance.

    Yahoo's v7 quote endpoint gates on a cookie + matching crumb token. We fetch
    a cookie from fc.yahoo.com, then exchange it for a crumb, and cache both.
    Pass ``force=True`` to rebuild after a rejected (e.g. expired) crumb.
    """
    global _yahoo_session, _yahoo_crumb, _yahoo_crumb_ts
    with _yahoo_lock:
        fresh = (time.monotonic() - _yahoo_crumb_ts) < _YAHOO_CRUMB_TTL_S
        if _yahoo_session is not None and _yahoo_crumb and fresh and not force:
            return _yahoo_session, _yahoo_crumb

        session = requests.Session()
        session.headers.update({"User-Agent": _YAHOO_UA})
        try:
            # Seed cookies (A1/A3); a non-200 here is fine as long as cookies are set.
            session.get(_YAHOO_COOKIE_URL, timeout=15)
            crumb_resp = session.get(_YAHOO_CRUMB_URL, timeout=15)
            crumb = crumb_resp.text.strip()
            # A valid crumb is a short token; HTML/empty means the handshake failed.
            if not crumb or "<" in crumb or len(crumb) > 64:
                logger.warning("Yahoo crumb handshake returned an unexpected token")
                return None, ""
            _yahoo_session = session
            _yahoo_crumb = crumb
            _yahoo_crumb_ts = time.monotonic()
            return _yahoo_session, _yahoo_crumb
        except Exception as e:
            logger.warning("Yahoo crumb handshake failed: %s", e)
            return None, ""


def _yahoo_quote(ticker: str) -> dict:
    """Fetch basic quote from Yahoo Finance (no API key needed).

    Uses a cached cookie + crumb handshake; retries once with a fresh handshake
    if the crumb was rejected (401/403).
    """
    for attempt in range(2):
        session, crumb = _yahoo_handshake(force=(attempt == 1))
        if session is None or not crumb:
            return {"error": "Yahoo Finance authentication (crumb) unavailable"}
        try:
            resp = session.get(
                _YAHOO_QUOTE_URL,
                params={"symbols": ticker, "crumb": crumb},
                timeout=15,
            )
            if resp.status_code in (401, 403) and attempt == 0:
                # Crumb likely expired — force a refresh and retry once.
                logger.info("Yahoo quote %s on first attempt, refreshing crumb", resp.status_code)
                continue
            resp.raise_for_status()
            data = resp.json()
            results = data.get("quoteResponse", {}).get("result", [])
            if not results:
                return {"error": f"No Yahoo Finance data for {ticker}"}
            q = results[0]
            return {
                "ticker": q.get("symbol", ticker),
                "name": q.get("shortName", ""),
                "price": q.get("regularMarketPrice", ""),
                "change_pct": q.get("regularMarketChangePercent", ""),
                "market_cap": q.get("marketCap", ""),
                "pe_ratio": q.get("trailingPE", ""),
                "volume": q.get("regularMarketVolume", ""),
            }
        except Exception as e:
            logger.warning("Yahoo Finance failed for %s: %s", ticker, e)
            return {"error": str(e)}
    return {"error": f"Yahoo Finance request failed for {ticker}"}


def search_sec_filings(company: str, filing_type: str = "10-K") -> list[dict]:
    """Search SEC EDGAR for company filings. Free API, no key needed.

    Args:
        company: Company name or ticker.
        filing_type: Filing type (10-K, 10-Q, 8-K, etc.).

    Returns:
        List of dicts with: title, filed_date, url, form_type.
    """
    try:
        url = "https://efts.sec.gov/LATEST/search-index"
        resp = requests.get(
            url,
            params={
                "q": company,
                "forms": filing_type,
                "dateRange": "custom",
                "startdt": "2023-01-01",
            },
            headers={"User-Agent": "Luminary-Research research@luminary.app"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        results = []
        for hit in hits[:10]:
            source = hit.get("_source", {})
            results.append({
                "title": source.get("display_names", [company])[0] if source.get("display_names") else company,
                "form_type": source.get("form_type", filing_type),
                "filed_date": source.get("file_date", ""),
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={company}&type={filing_type}&dateb=&owner=include&count=10",
            })
        return results
    except Exception as e:
        logger.warning("SEC EDGAR search failed for %s: %s", company, e)
        # Fallback: use EDGAR full-text search
        try:
            resp = requests.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": f'"{company}" AND "{filing_type}"'},
                headers={"User-Agent": "Luminary-Research research@luminary.app"},
                timeout=15,
            )
            if resp.ok:
                return [{"title": company, "form_type": filing_type, "note": "Fallback search"}]
        except Exception:
            pass
        return [{"error": str(e)}]
