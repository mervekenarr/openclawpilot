import os
import re
from urllib import error, parse, request


BLOCKED_HOST_TOKENS = {
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
    "wikipedia.org",
}


class CompanyDiscoveryError(RuntimeError):
    pass


def search_company_candidates(query: str, max_results: int = 10) -> list[dict]:
    normalized_query = (query or "").strip()
    if len(normalized_query) < 2:
        raise CompanyDiscoveryError("Gecerli bir arama sorgusu olmadan firma adayi bulunamaz.")

    candidates = []
    seen_domains: set[str] = set()

    for entry in _search_duckduckgo_entries(normalized_query, max_results=max_results):
        candidate = _build_candidate_from_entry(entry, source="web_search_result", query=normalized_query)
        key = _canonical_domain(candidate["website"])
        if key in seen_domains:
            continue
        seen_domains.add(key)
        candidates.append(candidate)

    return candidates


def discover_company_candidates(keyword: str, sector: str | None, limit: int) -> list[dict]:
    normalized_keyword = (keyword or "").strip()
    if len(normalized_keyword) < 2:
        raise CompanyDiscoveryError("Anahtar kelime olmadan guvenli firma aramasi yapilamaz.")

    normalized_sector = (sector or "").strip()
    queries = _build_candidate_queries(normalized_keyword, normalized_sector)
    scored_candidates: dict[str, tuple[int, dict]] = {}

    for query in queries:
        for entry in _search_duckduckgo_entries(query, max_results=max(limit * 4, 8)):
            company_name = _infer_company_name(entry["title"], entry["url"])
            score = _score_discovery_entry(entry, normalized_keyword, normalized_sector, company_name)
            key = _canonical_domain(entry["url"])
            candidate = _build_candidate_from_entry(
                entry,
                source="web_discovery",
                query=query,
            )

            previous = scored_candidates.get(key)
            if previous is None or score > previous[0]:
                scored_candidates[key] = (score, candidate)

    ranked = [item for _, item in sorted(scored_candidates.values(), key=lambda pair: pair[0], reverse=True)]
    filtered = [item for item in ranked if item["company_name"] and item["website"]]
    if not filtered:
        raise CompanyDiscoveryError("Guvenli web aramasinda uygun firma adayi bulunamadi.")

    return filtered[:limit]


def _build_candidate_from_entry(entry: dict, source: str, query: str | None = None) -> dict:
    return {
        "company_name": _infer_company_name(entry.get("title"), entry["url"]),
        "website": _root_website(entry["url"]),
        "source": source,
        "title": entry.get("title"),
        "snippet": entry.get("snippet"),
        "query": query,
    }


def discover_company_website(company_name: str) -> str:
    if not company_name.strip():
        raise CompanyDiscoveryError("Firma adi bos olamaz.")

    query = f'{company_name} official website'
    results = _search_duckduckgo_results(query)

    if not results:
        raise CompanyDiscoveryError("Resmi web sitesi otomatik bulunamadi. Website alanini manuel gir.")

    normalized_tokens = _normalize_company_tokens(company_name)

    scored_results = sorted(
        (
            (_score_candidate(url, normalized_tokens), url)
            for url in results
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    best_score, best_url = scored_results[0]
    if best_score <= 0:
        raise CompanyDiscoveryError("Guvenli bir resmi web sitesi otomatik secilemedi. Website alanini manuel gir.")

    return best_url


def _search_duckduckgo_results(query: str) -> list[str]:
    return [entry["url"] for entry in _search_duckduckgo_entries(query, max_results=10)]


def _search_duckduckgo_entries(query: str, max_results: int) -> list[dict]:
    encoded_query = parse.quote_plus(query)
    search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
    timeout_seconds = _get_env_int("SAFE_SITE_DISCOVERY_TIMEOUT", 8)
    user_agent = os.getenv(
        "SAFE_SITE_DISCOVERY_USER_AGENT",
        "OpenClawPilotDiscovery/0.1 (+safe-read-only)",
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
        raise CompanyDiscoveryError("Website arama servisine ulasilamadi.") from exc
    except TimeoutError as exc:
        raise CompanyDiscoveryError("Website arama istegi zaman asimina ugradi.") from exc

    link_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    entries: list[dict] = []
    seen: set[str] = set()

    for match in link_pattern.finditer(html):
        resolved_url = _resolve_duckduckgo_link(match.group("href"))
        if not resolved_url:
            continue

        if not _is_allowed_candidate(resolved_url):
            continue

        canonical = _canonical_domain(resolved_url)
        if canonical not in seen:
            seen.add(canonical)
            entries.append(
                {
                    "url": resolved_url,
                    "title": _clean_text(match.group("title")) or canonical,
                    "snippet": _extract_snippet_nearby(html, match.end()),
                }
            )

        if len(entries) >= max_results:
            break

    return entries


def _resolve_duckduckgo_link(raw_url: str) -> str | None:
    if raw_url.startswith("//"):
        raw_url = f"https:{raw_url}"

    parsed = parse.urlparse(raw_url)
    if "duckduckgo.com" in (parsed.netloc or ""):
        query_params = parse.parse_qs(parsed.query)
        target = query_params.get("uddg", [None])[0]
        if not target:
            return None
        raw_url = parse.unquote(target)

    normalized = raw_url.strip()
    if not normalized.startswith(("http://", "https://")):
        return None

    return normalized


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


def _is_allowed_candidate(url: str) -> bool:
    parsed = parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    if not host:
        return False

    return not any(token in host for token in BLOCKED_HOST_TOKENS)


def _normalize_company_tokens(company_name: str) -> list[str]:
    raw_tokens = re.findall(r"[a-z0-9]+", company_name.lower())
    ignored = {
        "sanayi",
        "ve",
        "ticaret",
        "ltd",
        "sti",
        "a",
        "s",
        "anonim",
        "sirketi",
        "limited",
    }
    tokens = [token for token in raw_tokens if token not in ignored and len(token) > 1]
    return tokens or raw_tokens


def _score_candidate(url: str, company_tokens: list[str]) -> int:
    host = parse.urlparse(url).netloc.lower()
    score = 0

    if host.startswith("www."):
        host = host[4:]

    for token in company_tokens:
        if token in host:
            score += 4

    if host.endswith(".com"):
        score += 2
    if host.endswith(".com.tr"):
        score += 3

    return score


def _score_discovery_entry(
    entry: dict,
    keyword: str,
    sector: str,
    company_name: str,
) -> int:
    text = " ".join(
        part for part in [entry.get("title"), entry.get("snippet"), entry.get("url"), company_name]
        if part
    ).lower()
    score = 0

    if keyword.lower() in text:
        score += 5
    if sector and sector.lower() in text:
        score += 3
    if any(token in text for token in ["valve", "vana", "flow", "industry", "industrial", "metal", "manufacturing"]):
        score += 2

    score += _score_candidate(entry["url"], _normalize_company_tokens(company_name))
    return score


def _infer_company_name(title: str | None, url: str) -> str:
    if title:
        primary = re.split(r"\s[\-|–—|]\s", title, maxsplit=1)[0].strip()
        primary = re.sub(r"\b(official website|homepage|anasayfa)\b", "", primary, flags=re.IGNORECASE).strip()
        if len(primary) >= 2:
            return primary

    host = _canonical_domain(url)
    label = host.split(".")[0].replace("-", " ").strip()
    return " ".join(part.capitalize() for part in label.split())


def _canonical_domain(url: str) -> str:
    host = parse.urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _root_website(url: str) -> str:
    parsed = parse.urlparse(url)
    host = parsed.netloc
    return f"{parsed.scheme}://{host}"


def _build_candidate_queries(keyword: str, sector: str) -> list[str]:
    base_parts = [keyword]
    if sector:
        base_parts.append(sector)

    base = " ".join(base_parts)
    queries = [
        f'{base} manufacturer company Turkey',
        f'{base} industrial supplier official website',
        f'{base} site:.com.tr',
    ]

    deduped = []
    seen = set()
    for item in queries:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = re.sub(r"<[^>]+>", " ", value)
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
