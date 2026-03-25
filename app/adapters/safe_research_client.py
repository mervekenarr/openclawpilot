import os
import re
from html import unescape
from urllib import error, parse, request


class SafeResearchError(RuntimeError):
    pass


def fetch_company_website_summary(website_url: str, company_name: str) -> dict:
    normalized_url = _normalize_url(website_url)
    timeout_seconds = _get_env_int("SAFE_WEB_RESEARCH_TIMEOUT", 6)
    user_agent = os.getenv(
        "SAFE_WEB_RESEARCH_USER_AGENT",
        "OpenClawPilotResearch/0.1 (+safe-read-only)",
    )
    html, final_url, content_type = _fetch_html_document(
        normalized_url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
    )

    if "html" not in content_type.lower():
        raise SafeResearchError("Web sitesi HTML donmedi.")

    title = _extract_title(html)
    meta_description = _extract_meta_description(html)
    headings = _extract_headings(html)
    text_excerpt = _extract_text_excerpt(html)
    related_pages = _fetch_related_pages(
        html=html,
        base_url=final_url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
    )
    combined_excerpt = _build_combined_excerpt(text_excerpt, related_pages)
    relevance = _estimate_relevance(text_excerpt, company_name)
    best_summary = _choose_best_summary(meta_description, combined_excerpt or text_excerpt, title)

    return {
        "source_type": "company_website",
        "requested_url": normalized_url,
        "final_url": final_url,
        "title": title,
        "meta_description": meta_description,
        "headings": headings,
        "text_excerpt": combined_excerpt or text_excerpt,
        "best_summary": best_summary,
        "relevance": relevance,
        "related_pages": related_pages,
    }


def _fetch_html_document(url: str, user_agent: str, timeout_seconds: int) -> tuple[str, str, str]:
    http_request = request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            body = response.read(220_000)
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
    except error.HTTPError as exc:
        raise SafeResearchError(f"Web sitesi HTTP hatasi dondu: {exc.code}") from exc
    except error.URLError as exc:
        raise SafeResearchError("Web sitesi okunamadi veya ulasilamiyor.") from exc
    except TimeoutError as exc:
        raise SafeResearchError("Web sitesi istegi zaman asimina ugradi.") from exc

    return body.decode("utf-8", errors="ignore"), final_url, content_type


def _normalize_url(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise SafeResearchError("Web sitesi adresi bos.")

    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    parsed = parse.urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SafeResearchError("Web sitesi adresi gecersiz.")

    return normalized


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    return _clean_text(match.group(1))


def _extract_meta_description(html: str) -> str | None:
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _clean_text(match.group(1))

    return None


def _extract_headings(html: str) -> list[str]:
    matches = re.findall(r"<h[1-2][^>]*>(.*?)</h[1-2]>", html, flags=re.IGNORECASE | re.DOTALL)
    cleaned = []
    for item in matches[:3]:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


def _extract_text_excerpt(html: str) -> str | None:
    without_scripts = re.sub(r"<script.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    without_styles = re.sub(r"<style.*?</style>", " ", without_scripts, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", without_styles)
    text = _clean_text(text)
    if not text:
        return None

    return text[:420]


def _estimate_relevance(text_excerpt: str | None, company_name: str) -> str:
    if not text_excerpt:
        return "low"

    lowered_excerpt = text_excerpt.lower()
    lowered_company = company_name.lower()
    if lowered_company in lowered_excerpt:
        return "high"
    if len(lowered_excerpt) > 120:
        return "medium"
    return "low"


def _fetch_related_pages(
    html: str,
    base_url: str,
    user_agent: str,
    timeout_seconds: int,
) -> list[dict]:
    if not _get_env_flag("SAFE_WEB_RESEARCH_FOLLOW_ABOUT", True):
        return []

    candidate_urls = _extract_priority_links(html, base_url)
    related_pages = []

    for url in candidate_urls[:1]:
        try:
            related_html, final_url, content_type = _fetch_html_document(
                url,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
            )
        except SafeResearchError:
            continue

        if "html" not in content_type.lower():
            continue

        related_pages.append(
            {
                "url": final_url,
                "title": _extract_title(related_html),
                "excerpt": _extract_text_excerpt(related_html),
            }
        )

    return related_pages


def _extract_priority_links(html: str, base_url: str) -> list[str]:
    anchor_pattern = re.compile(
        r'<a[^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<label>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    priority_tokens = [
        "about",
        "about-us",
        "company",
        "corporate",
        "kurumsal",
        "hakkimizda",
        "hakkımızda",
    ]
    base_host = parse.urlparse(base_url).netloc.lower()
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()

    for match in anchor_pattern.finditer(html):
        raw_href = (match.group("href") or "").strip()
        label = _clean_text(match.group("label")) or ""
        if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:")):
            continue

        absolute_url = parse.urljoin(base_url, raw_href)
        parsed = parse.urlparse(absolute_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != base_host:
            continue

        haystack = f"{absolute_url.lower()} {label.lower()}"
        score = sum(3 for token in priority_tokens if token in haystack)
        if score <= 0:
            continue

        normalized = absolute_url.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append((score, normalized))

    return [url for _, url in sorted(candidates, key=lambda item: item[0], reverse=True)]


def _build_combined_excerpt(text_excerpt: str | None, related_pages: list[dict]) -> str | None:
    parts = []
    if text_excerpt:
        parts.append(text_excerpt)

    for page in related_pages:
        excerpt = page.get("excerpt")
        if excerpt:
            parts.append(excerpt)

    if not parts:
        return None

    combined = " ".join(parts)
    combined = re.sub(r"\s+", " ", combined).strip()
    return combined[:600]


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = unescape(value)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _choose_best_summary(
    meta_description: str | None,
    text_excerpt: str | None,
    title: str | None,
) -> str | None:
    if meta_description and not _is_low_signal_summary(meta_description):
        return meta_description

    if text_excerpt and not _is_low_signal_summary(text_excerpt):
        return text_excerpt[:300]

    if title and not _is_low_signal_summary(title):
        return title

    return None


def _is_low_signal_summary(value: str) -> bool:
    normalized = value.strip().lower()
    if len(normalized) < 12:
        return True

    low_signal_values = {
        "en",
        "tr",
        "english",
        "turkish",
        "home",
        "homepage",
    }
    return normalized in low_signal_values


def _get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        return int(raw_value.strip())
    except ValueError:
        return default


def _get_env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
