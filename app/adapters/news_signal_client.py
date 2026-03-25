import os
import re
from html import unescape
from urllib import error, parse, request


BLOCKED_HOST_TOKENS = {
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
}


class SafeNewsSearchError(RuntimeError):
    pass


def search_company_news_signals(
    company_name: str,
    keyword: str | None = None,
    max_results: int = 3,
) -> list[dict]:
    normalized_company = (company_name or "").strip()
    if not normalized_company:
        raise SafeNewsSearchError("Firma adi olmadan haber aramasi yapilamaz.")

    query_parts = [f'"{normalized_company}"']
    if keyword:
        query_parts.append(keyword.strip())
    query_parts.append("news")

    encoded_query = parse.quote_plus(" ".join(part for part in query_parts if part))
    search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
    timeout_seconds = _get_env_int("SAFE_NEWS_SEARCH_TIMEOUT", 8)
    user_agent = os.getenv(
        "SAFE_NEWS_SEARCH_USER_AGENT",
        "OpenClawPilotNews/0.1 (+safe-read-only)",
    )
    search_request = request.Request(
        search_url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )

    try:
        with request.urlopen(search_request, timeout=timeout_seconds) as response:
            html = response.read(300_000).decode("utf-8", errors="ignore")
    except error.URLError as exc:
        raise SafeNewsSearchError("Haber arama servisine ulasilamadi.") from exc
    except TimeoutError as exc:
        raise SafeNewsSearchError("Haber arama istegi zaman asimina ugradi.") from exc

    return _extract_news_results(html, max_results=max_results)


def _extract_news_results(html: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    link_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    for match in link_pattern.finditer(html):
        resolved_url = _resolve_duckduckgo_link(match.group("href"))
        if not resolved_url or not _is_allowed_candidate(resolved_url):
            continue
        if resolved_url in seen_urls:
            continue

        title = _clean_text(match.group("title"))
        snippet = _extract_snippet_nearby(html, match.end())
        if not title:
            continue

        results.append(
            {
                "source_type": "news_scan",
                "url": resolved_url,
                "title": title,
                "snippet": snippet,
                "published_at": None,
            }
        )
        seen_urls.add(resolved_url)

        if len(results) >= max_results:
            break

    return results


def _extract_snippet_nearby(html: str, start_index: int) -> str | None:
    window = html[start_index : start_index + 900]
    match = re.search(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(.*?)</div>',
        window,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None

    return _clean_text(match.group(1) or match.group(2))


def _resolve_duckduckgo_link(raw_url: str) -> str | None:
    normalized = raw_url.strip()
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"

    parsed = parse.urlparse(normalized)
    if "duckduckgo.com" in (parsed.netloc or ""):
        query_params = parse.parse_qs(parsed.query)
        target = query_params.get("uddg", [None])[0]
        if not target:
            return None
        normalized = parse.unquote(target)

    if not normalized.startswith(("http://", "https://")):
        return None

    return normalized


def _is_allowed_candidate(url: str) -> bool:
    host = (parse.urlparse(url).netloc or "").lower()
    if not host:
        return False

    return not any(token in host for token in BLOCKED_HOST_TOKENS)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = unescape(value)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        return int(raw_value.strip())
    except ValueError:
        return default
