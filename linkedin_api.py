"""
LinkedIn Messaging API
Receives leads from n8n and sends LinkedIn messages via Playwright.
Port: 8502

Strategy:
1. If the company page exposes a "Message" button, send directly.
2. Otherwise go to the employees page, find a reachable person, and try there.
"""

from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import logging
import json
import os
import random
import re
import threading
import time
import unicodedata
from urllib.parse import quote, unquote, urlparse


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("linkedin-api")

app = Flask(__name__)

LINKEDIN_TOKEN = os.getenv("LINKEDIN_SESSION_TOKEN", "")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("LINKEDIN_REQUEST_TIMEOUT", "85"))
NAVIGATION_TIMEOUT_MS = int(os.getenv("LINKEDIN_NAV_TIMEOUT_MS", "20000"))
MAX_EMPLOYEE_CANDIDATES = int(os.getenv("LINKEDIN_MAX_EMPLOYEE_CANDIDATES", "2"))
MIN_REQUEST_GAP_SECONDS = float(os.getenv("LINKEDIN_MIN_GAP_SECONDS", "6"))
RATE_LIMIT_BACKOFF_SECONDS = float(os.getenv("LINKEDIN_RATE_LIMIT_BACKOFF_SECONDS", "18"))
DEBUG_SCREENSHOTS_ENABLED = os.getenv("LINKEDIN_DEBUG_SCREENSHOTS", "false").strip().lower() in {"1", "true", "yes", "on"}
LOG_SENSITIVE_DATA = os.getenv("LINKEDIN_LOG_SENSITIVE_DATA", "false").strip().lower() in {"1", "true", "yes", "on"}
LINKEDIN_PERSISTENT_SESSION = os.getenv("LINKEDIN_PERSISTENT_SESSION", "true").strip().lower() in {"1", "true", "yes", "on"}
LINKEDIN_USER_DATA_DIR = os.getenv("LINKEDIN_USER_DATA_DIR", "/app/runtime-home/linkedin-profile").strip() or "/app/runtime-home/linkedin-profile"
LINKEDIN_STORAGE_STATE_PATH = os.getenv("LINKEDIN_STORAGE_STATE_PATH", "/app/runtime-home/linkedin-storage-state.json").strip() or "/app/runtime-home/linkedin-storage-state.json"

_lock = threading.Lock()
_last_request_finished_at = 0.0


def time_left(deadline):
    return deadline - time.monotonic()


def ensure_time_budget(deadline, minimum_seconds, stage):
    remaining = time_left(deadline)
    if remaining < minimum_seconds:
        raise TimeoutError(f"Time budget exceeded during {stage} ({remaining:.1f}s left)")


def human_delay(min_ms=800, max_ms=2000, deadline=None):
    delay_s = random.uniform(min_ms, max_ms) / 1000
    if deadline is not None:
        remaining = time_left(deadline)
        if remaining <= 0:
            return False
        delay_s = min(delay_s, max(0, remaining - 0.2))
    if delay_s <= 0:
        return False
    time.sleep(delay_s)
    return True


def enforce_request_spacing(deadline):
    global _last_request_finished_at
    if MIN_REQUEST_GAP_SECONDS <= 0:
        return

    remaining_gap = MIN_REQUEST_GAP_SECONDS - (time.monotonic() - _last_request_finished_at)
    if remaining_gap <= 0:
        return

    ensure_time_budget(deadline, remaining_gap + 1, "linkedin request spacing")
    log.info("Waiting %.1fs before the next LinkedIn company to reduce rate limiting", remaining_gap)
    time.sleep(remaining_gap)


def mask_company_name(value):
    text = (value or "").strip()
    if not text:
        return "unknown-company"
    if LOG_SENSITIVE_DATA:
        return text
    if len(text) <= 4:
        return text[0] + "***" if text else "unknown-company"
    return f"{text[:2]}***{text[-2:]}"


def mask_url(url):
    text = (url or "").strip()
    if not text:
        return "unknown-url"
    if LOG_SENSITIVE_DATA:
        return text

    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = parsed.netloc or parsed.path.split("/")[0] or "unknown-host"
    path = parsed.path.strip("/")
    if not path:
        return host

    parts = [part for part in path.split("/") if part]
    last = parts[-1] if parts else ""
    if len(last) > 6:
        last = f"{last[:3]}***{last[-2:]}"
    elif last:
        last = f"{last[:1]}***"
    return f"{host}/.../{last}" if last else host


def sanitize_error_text(value):
    text = str(value or "")
    if LOG_SENSITIVE_DATA:
        return text
    text = re.sub(r"https?://[^\s)\"']+", "[redacted-url]", text)
    text = re.sub(r"www\.[^\s)\"']+", "[redacted-url]", text)
    return text


def ensure_profile_dir():
    if not LINKEDIN_USER_DATA_DIR:
        return ""
    os.makedirs(LINKEDIN_USER_DATA_DIR, exist_ok=True)
    return LINKEDIN_USER_DATA_DIR


def load_storage_state():
    if not LINKEDIN_STORAGE_STATE_PATH or not os.path.exists(LINKEDIN_STORAGE_STATE_PATH):
        return {}
    try:
        with open(LINKEDIN_STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Could not read LinkedIn storage state file: %s", sanitize_error_text(exc))
        return {}


def has_storage_state():
    return bool(load_storage_state())


def has_linkedin_auth():
    return bool(LINKEDIN_TOKEN) or has_storage_state()


def normalize_text(value):
    if not value:
        return ""
    return (
        value.lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ğ", "g")
        .replace("Ğ", "g")
        .replace("ü", "u")
        .replace("Ü", "u")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ç", "c")
        .replace("Ç", "c")
        .strip()
    )


def derive_company_name(company_url):
    slug = unquote((company_url or "").split("/company/")[-1].split("/")[0].strip())
    return slug.replace("-", " ").replace("_", " ").title() or "LinkedIn Company"


def ascii_slugify(value):
    raw = unquote((value or "").strip()).lower()
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug


def normalize_linkedin_company_url(company_url):
    raw = (company_url or "").strip()
    if not raw:
        return raw
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("www."):
        raw = "https://" + raw
    elif raw.startswith("linkedin.com/"):
        raw = "https://www." + raw

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    path = parsed.path or ""
    match = re.search(r"/company/([^/?#]+)/?", path, re.IGNORECASE)
    if not match:
        return raw
    slug = quote(unquote(match.group(1)).strip(), safe="-")
    return f"https://www.linkedin.com/company/{slug}/"


def build_company_url_variants(company_url):
    raw = (company_url or "").strip()
    if not raw:
        return []

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    path = parsed.path or ""
    match = re.search(r"/company/([^/?#]+)/?", path, re.IGNORECASE)
    if not match:
        normalized = normalize_linkedin_company_url(raw)
        return [normalized] if normalized else [raw]

    original_slug = unquote(match.group(1)).strip()
    suffix = path[match.end():].strip("/")
    slug_candidates = []
    for slug in [original_slug, ascii_slugify(original_slug)]:
        if slug and slug not in slug_candidates:
            slug_candidates.append(slug)

    variants = []
    for slug in slug_candidates:
        candidate = f"https://www.linkedin.com/company/{quote(slug, safe='-')}/"
        if suffix:
            candidate += f"{suffix}/"
        if candidate not in variants:
            variants.append(candidate)
    return variants


def page_has_auth_wall(page):
    try:
        current_url = (page.url or "").lower()
    except Exception:
        current_url = ""

    if any(token in current_url for token in ["/checkpoint/", "/login", "/uas/login", "authwall"]):
        return True

    try:
        body_text = normalize_text((page.locator("body").inner_text(timeout=1500) or "")[:800])
    except Exception:
        body_text = ""

    auth_tokens = [
        "sign in",
        "join now",
        "oturum ac",
        "giris yap",
        "hesabinizi dogrulayin",
        "dogrulamaniz gerekiyor",
    ]
    return any(token in body_text for token in auth_tokens)


def page_has_rate_limit(page):
    try:
        current_url = (page.url or "").lower()
    except Exception:
        current_url = ""

    if "error-1015" in current_url or "rate" in current_url and "limit" in current_url:
        return True

    try:
        body_text = normalize_text((page.locator("body").inner_text(timeout=1500) or "")[:1600])
    except Exception:
        body_text = ""

    rate_limit_tokens = [
        "error 1015",
        "you are being rate limited",
        "rate limit",
        "too many requests",
        "unusual activity",
        "try again later",
    ]
    return any(token in body_text for token in rate_limit_tokens)


def inspect_company_page_state(page):
    if page_has_rate_limit(page):
        return False, "rate_limit"

    selectors = [
        "h1",
        'button:has-text("Mesaj")',
        'button:has-text("Message")',
        'a[href*="/about/"]',
        'a[href*="/posts/"]',
        'a[href*="/people/"]',
        'a[href*="/jobs/"]',
        ".org-top-card",
        ".artdeco-card",
    ]

    for sel in selectors:
        try:
            node = page.query_selector(sel)
            if node and node.is_visible():
                return True, f"selector:{sel}"
        except Exception:
            pass

    if page_has_auth_wall(page):
        return False, "auth_wall"

    try:
        current_url = (page.url or "").lower()
    except Exception:
        current_url = ""

    try:
        body_text = normalize_text((page.locator("body").inner_text(timeout=1500) or "")[:1200])
    except Exception:
        body_text = ""

    if "/company/" in current_url and len(body_text) > 120:
        company_markers = [
            "takip et",
            "genel bakis",
            "overview",
            "gonderiler",
            "hakkinda",
            "calisan",
            "employees on linkedin",
            "is ilanlari",
            "people",
        ]
        if any(token in body_text for token in company_markers):
            return True, "body_markers"
        return True, "body_present"

    return False, "not_ready"


def wait_for_company_page_shell(page, timeout_ms=7000):
    end_at = time.monotonic() + (timeout_ms / 1000)
    last_reason = "not_ready"
    while time.monotonic() < end_at:
        ready, reason = inspect_company_page_state(page)
        if ready:
            return True, reason
        last_reason = reason
        human_delay(300, 500)
    return False, last_reason


def resolve_company_page_via_search(page, company_name, deadline):
    if not company_name:
        return ""

    ensure_time_budget(deadline, 8, "linkedin company search fallback")
    search_url = (
        "https://www.linkedin.com/search/results/companies/?keywords="
        + quote(company_name)
        + "&origin=GLOBAL_SEARCH_HEADER"
    )
    log.info("Trying company search fallback for %s", mask_company_name(company_name))
    page.goto(search_url, timeout=min(12000, int(time_left(deadline) * 1000) - 500), wait_until="commit")
    human_delay(1200, 1800, deadline=deadline)

    try:
        page.wait_for_selector("a[href*='/company/']", timeout=6000)
    except Exception:
        pass

    for link in page.query_selector_all("a[href*='/company/']"):
        try:
            href = link.get_attribute("href") or ""
            if "/company/" not in href:
                continue
            clean = normalize_linkedin_company_url(href)
            if clean:
                log.info("Resolved company URL via search: %s", mask_url(clean))
                return clean
        except Exception:
            pass
    return ""


def resolve_people_via_search(page, company_name, deadline):
    if not company_name:
        return []

    ensure_time_budget(deadline, 8, "linkedin people search fallback")
    search_url = (
        "https://www.linkedin.com/search/results/people/?keywords="
        + quote(company_name)
        + "&origin=GLOBAL_SEARCH_HEADER"
    )
    log.info("Trying people search fallback for %s", mask_company_name(company_name))
    page.goto(search_url, timeout=min(12000, int(time_left(deadline) * 1000) - 500), wait_until="commit")
    human_delay(1200, 1800, deadline=deadline)

    candidates = []
    seen = set()
    try:
        hrefs = page.eval_on_selector_all(
            "a[href*='/in/']",
            "els => els.map(el => el.getAttribute('href')).filter(Boolean)",
        )
    except Exception:
        hrefs = []

    for href in hrefs:
        if "/in/" not in href:
            continue
        base = href.split("?")[0]
        clean = "https://www.linkedin.com" + base if base.startswith("/") else base
        if clean in seen:
            continue
        seen.add(clean)
        candidates.append(clean)
        if len(candidates) >= MAX_EMPLOYEE_CANDIDATES:
            break

    return candidates


def goto_with_retries(page, url, deadline, stage, minimum_seconds=8):
    ensure_time_budget(deadline, minimum_seconds, stage)
    attempts = build_company_url_variants(url)
    if url and url not in attempts:
        attempts.append(url)

    last_error = None
    for index, candidate in enumerate(attempts, start=1):
        timeout_ms = max(
            8000,
            min(NAVIGATION_TIMEOUT_MS + (5000 if index > 1 else 0), int(time_left(deadline) * 1000) - 500),
        )
        try:
            log.info("Navigating to %s (%s, attempt %s)", mask_url(candidate), stage, index)
            page.goto(candidate, timeout=timeout_ms, wait_until="commit")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=min(5000, timeout_ms))
            except Exception:
                pass
            if "company" in stage:
                shell_ready, shell_reason = wait_for_company_page_shell(page, timeout_ms=min(7000, timeout_ms))
                if not shell_ready and shell_reason == "auth_wall":
                    save_debug_screenshot(page, "debug_company_auth_wall.png")
                    raise TimeoutError(f"LinkedIn auth wall encountered for {mask_url(candidate)}")
                if not shell_ready and shell_reason == "rate_limit":
                    save_debug_screenshot(page, "debug_company_rate_limit.png")
                    raise TimeoutError(f"LinkedIn rate limit encountered for {mask_url(candidate)}")
                if not shell_ready:
                    log.info("Company shell not fully ready for %s; proceeding anyway (%s)", mask_url(candidate), shell_reason)
                else:
                    log.info("Company shell ready for %s via %s", mask_url(candidate), shell_reason)
            return candidate
        except Exception as exc:
            last_error = exc
            log.warning("Navigation failed for %s (%s): %s", mask_url(candidate), stage, sanitize_error_text(exc))
            if "ERR_TOO_MANY_REDIRECTS" in str(exc):
                human_delay(
                    int(RATE_LIMIT_BACKOFF_SECONDS * 1000),
                    int((RATE_LIMIT_BACKOFF_SECONDS + 4) * 1000),
                    deadline=deadline,
                )
            human_delay(700, 1200, deadline=deadline)

    raise last_error or TimeoutError(f"Could not open {stage}")


def find_clickable_by_tokens(page, include_tokens, exclude_tokens=None):
    exclude_tokens = exclude_tokens or []
    selectors = [
        "button",
        "a[role='button']",
        "div[role='button']",
        "span[role='button']",
    ]

    for sel in selectors:
        try:
            for candidate in page.query_selector_all(sel):
                try:
                    if not candidate.is_visible():
                        continue
                    text = normalize_text(candidate.inner_text())
                    aria = normalize_text(candidate.get_attribute("aria-label") or "")
                    title = normalize_text(candidate.get_attribute("title") or "")
                    combined = " ".join(part for part in [text, aria, title] if part)
                    if not combined:
                        continue
                    if any(token in combined for token in include_tokens) and not any(
                        token in combined for token in exclude_tokens
                    ):
                        return candidate
                except Exception:
                    pass
        except Exception:
            pass
    return None


def is_share_overlay(page):
    patterns = [
        "gonderisini gonder",
        "postunu gonder",
        "send post",
        "send this post",
        "share post",
    ]
    selectors = [
        "div[role='dialog']",
        ".msg-overlay-conversation-bubble",
        ".artdeco-modal",
    ]
    for sel in selectors:
        try:
            node = page.query_selector(sel)
            if node and node.is_visible():
                text = normalize_text((node.inner_text() or "")[:400])
                if any(pattern in text for pattern in patterns):
                    return True
        except Exception:
            pass
    return False


def close_overlay_if_needed(page, deadline):
    close_selectors = [
        'button[aria-label*="Kapat"]',
        'button[aria-label*="Close"]',
        'button.artdeco-modal__dismiss',
        '.msg-overlay-bubble-header__control',
        'button:has-text("Vazgec")',
        'button:has-text("Cancel")',
    ]
    for sel in close_selectors:
        try:
            button = page.query_selector(sel)
            if button and button.is_visible():
                button.click()
                human_delay(250, 450, deadline=deadline)
                return True
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
        human_delay(250, 450, deadline=deadline)
        return True
    except Exception:
        return False


def get_company_message_button_candidates(page):
    try:
        page.evaluate("window.scrollTo(0, 0)")
        human_delay(250, 400)
    except Exception:
        pass

    candidates = []
    selectors = [
        "button",
        "a[role='button']",
        "div[role='button']",
        "span[role='button']",
    ]
    for sel in selectors:
        try:
            for candidate in page.query_selector_all(sel):
                try:
                    if not candidate.is_visible():
                        continue
                    text = normalize_text(candidate.inner_text())
                    aria = normalize_text(candidate.get_attribute("aria-label") or "")
                    title = normalize_text(candidate.get_attribute("title") or "")
                    combined = " ".join(part for part in [text, aria, title] if part)
                    # Accept exact "mesaj"/"message" or text containing "mesaj"/"message" as a word
                    is_message_btn = (
                        combined in ("mesaj", "message")
                        or "mesaj" in combined.split()
                        or "message" in combined.split()
                        or " mesaj" in combined
                        or " message" in combined
                    )
                    if not is_message_btn:
                        continue
                    if any(
                        token in combined
                        for token in ["gonderi", "paylas", "share", "send post", "gonderisini gonder"]
                    ):
                        continue
                    box = candidate.bounding_box() or {}
                    y = box.get("y", 9999)
                    x = box.get("x", 9999)
                    if y > 380:
                        continue
                    # x filter removed — LinkedIn CTA buttons can appear anywhere horizontally
                    # depending on viewport and page layout
                    candidates.append((y, x, candidate))
                except Exception:
                    pass
        except Exception:
            pass

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in candidates]


def find_company_message_button(page):
    candidates = get_company_message_button_candidates(page)
    if candidates:
        return candidates[0]
    return find_clickable_by_tokens(
        page,
        include_tokens=["mesaj", "message"],
        exclude_tokens=["mesaj gonder", "send message", "olustur", "compose", "paylas", "share"],
    )


def find_company_message_button_via_more_menu(page, deadline):
    more_button = find_clickable_by_tokens(
        page,
        include_tokens=["daha fazla", "more"],
        exclude_tokens=["more filters", "filtre"],
    )
    if not more_button:
        return None

    try:
        more_button.scroll_into_view_if_needed()
    except Exception:
        pass

    for action_name, action in [
        ("standard", lambda: more_button.click()),
        ("force", lambda: more_button.click(force=True)),
        ("dom", lambda: page.evaluate("(el) => el.click()", more_button)),
    ]:
        try:
            action()
            log.info("Opened more-actions menu via %s click", action_name)
        except Exception:
            continue

        human_delay(250, 500, deadline=deadline)

        message_candidate = find_clickable_by_tokens(
            page,
            include_tokens=["mesaj", "message"],
            exclude_tokens=["mesaj gonder", "send message", "paylas", "share"],
        )
        if message_candidate and message_candidate != more_button:
            return message_candidate

    return None


def find_message_input(page):
    selectors = [
        # Modern LinkedIn messaging composer (2024+)
        ".msg-form__contenteditable[contenteditable='true']",
        ".msg-form__contenteditable[role='textbox']",
        ".msg-form__contenteditable",
        # Overlay bubble (chat popup)
        ".msg-overlay-conversation-bubble [contenteditable='true']",
        ".msg-overlay-conversation-bubble div[role='textbox']",
        ".msg-overlay-conversation-bubble .msg-form__contenteditable",
        ".msg-overlay-conversation-bubble textarea",
        # Content container wrappers
        ".msg-form__msg-content-container .msg-form__contenteditable",
        ".msg-form__msg-content-container [contenteditable='true']",
        ".msg-form__msg-content-container div[role='textbox']",
        # Modal / dialog variants
        'div[role="dialog"] [contenteditable="true"]',
        'div[role="dialog"] [role="textbox"]',
        'div[role="dialog"] textarea',
        'div[role="dialog"] textarea[placeholder*="mesaj"]',
        'div[role="dialog"] textarea[placeholder*="Mesaj"]',
        'div[role="dialog"] textarea[placeholder*="message"]',
        'div[role="dialog"] textarea[placeholder*="yaz"]',
        ".artdeco-modal [contenteditable='true']",
        ".artdeco-modal textarea",
        # Generic placeholder-based selectors
        'textarea[placeholder*="mesaj"]',
        '[contenteditable="true"][placeholder*="mesaj"]',
        'textarea[placeholder*="Message"]',
        '[contenteditable="true"][placeholder*="Message"]',
        'textarea[placeholder*="yaz"]',
        'textarea[placeholder*="Write"]',
        # Broad fallbacks
        "[contenteditable='true']",
        "textarea",
        'div[role="textbox"]',
    ]

    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return el
        except Exception:
            pass
    return None


def prime_message_surface(page, deadline):
    """Activate LinkedIn's inline composer when the surface exists but the editor is not yet obvious."""
    click_selectors = [
        ".msg-form__contenteditable",
        ".msg-form__msg-content-container",
        ".msg-overlay-conversation-bubble .msg-form__msg-content-container",
        ".msg-overlay-conversation-bubble",
        ".msg-form__placeholder",
        ".msg-form__container",
        ".msg-overlay-conversation-bubble-footer",
    ]

    for sel in click_selectors:
        try:
            candidate = page.query_selector(sel)
            if candidate and candidate.is_visible():
                try:
                    candidate.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    candidate.click()
                except Exception:
                    try:
                        candidate.click(force=True)
                    except Exception:
                        continue
                human_delay(250, 450, deadline=deadline)
                textarea = find_message_input(page)
                if textarea:
                    log.info("Message input activated via selector %s", sel)
                    return textarea
        except Exception:
            pass

    recipient_selectors = [
        '.msg-connections-typeahead__search-field',
        '.msg-overlay-conversation-bubble input',
        'input[placeholder*="alici"]',
        'input[placeholder*="recipient"]',
    ]
    for sel in recipient_selectors:
        try:
            field = page.query_selector(sel)
            if field and field.is_visible():
                field.focus()
                page.keyboard.press("Tab")
                human_delay(250, 450, deadline=deadline)
                textarea = find_message_input(page)
                if textarea:
                    log.info("Message input activated by tabbing from recipient field")
                    return textarea
        except Exception:
            pass

    return None


def has_message_surface(page):
    if is_share_overlay(page):
        return False

    if find_message_input(page):
        return True

    url = (page.url or "").lower()
    if "/messaging/" in url or "/messaging" == url.rstrip("/"):
        return True

    selectors = [
        'div[role="dialog"]',
        ".artdeco-modal",
        ".msg-overlay-conversation-bubble",
        ".msg-form__msg-content-container",
        ".msg-form__container",
        ".msg-connections-typeahead__search-field",
        'text="Yeni mesaj"',
        'text="New message"',
        'text="Kime:"',
        'text="To:"',
    ]
    for sel in selectors:
        try:
            node = page.query_selector(sel)
            if node and node.is_visible():
                return True
        except Exception:
            pass
    return False


def activate_message_ui(page, msg_btn, deadline):
    href = ""
    try:
        href = (msg_btn.get_attribute("href") or "").strip()
    except Exception:
        href = ""

    actions = [
        ("standard", lambda: msg_btn.click()),
        ("force", lambda: msg_btn.click(force=True)),
        ("dom", lambda: page.evaluate("(el) => el.click()", msg_btn)),
        ("enter", lambda: (msg_btn.focus(), page.keyboard.press("Enter"))),
    ]

    # Track if this button is known to open a share overlay — bail out early if so
    button_opens_share = False

    for name, action in actions:
        if time_left(deadline) < 2:
            return False
        if button_opens_share:
            break
        try:
            action()
            log.info("Triggered message button via %s click", name)
        except Exception as exc:
            log.info("Message button %s click failed: %s", name, exc)
            continue

        for _ in range(4):
            human_delay(350, 650, deadline=deadline)
            if is_share_overlay(page):
                log.info("Detected share/send-post overlay after %s click; closing it — button is not the message button", name)
                close_overlay_if_needed(page, deadline)
                button_opens_share = True  # Don't retry with same button
                break
            if has_message_surface(page):
                log.info("Message surface detected after %s click", name)
                return True

    if href and "linkedin.com" in href and "/messaging" in href:
        try:
            target = href if href.startswith("http") else f"https://www.linkedin.com{href}"
            log.info("Navigating directly to messaging href: %s", mask_url(target))
            page.goto(target, timeout=min(12000, int(time_left(deadline) * 1000) - 500), wait_until="commit")
            for _ in range(6):
                human_delay(400, 700, deadline=deadline)
                if is_share_overlay(page):
                    log.info("Direct messaging navigation led to share overlay; closing it")
                    close_overlay_if_needed(page, deadline)
                    break
                if has_message_surface(page):
                    log.info("Message surface detected after direct messaging navigation")
                    return True
        except Exception as exc:
            log.info("Direct messaging navigation failed: %s", sanitize_error_text(exc))

    return False


def wait_for_message_dialog(page, deadline):
    for _ in range(7):
        if time_left(deadline) < 2:
            return None
        human_delay(500, 900, deadline=deadline)

        textarea = find_message_input(page)
        if textarea:
            return textarea

        if has_message_surface(page):
            textarea = prime_message_surface(page, deadline)
            if textarea:
                return textarea

        url = (page.url or "").lower()
        if "/messaging/" in url or "/messaging" == url.rstrip("/"):
            human_delay(600, 900, deadline=deadline)
            textarea = find_message_input(page)
            if textarea:
                return textarea

        try:
            dialog = page.query_selector('div[role="dialog"]')
            if dialog and dialog.is_visible():
                for sel in ["textarea", '[contenteditable="true"]', '[role="textbox"]']:
                    el = dialog.query_selector(sel)
                    if el and el.is_visible():
                        return el
        except Exception:
            pass

    return None


def ensure_people_page(page, company_url, deadline):
    current_url = (page.url or "").lower()
    if "/people/" in current_url:
        return True

    people_link = None
    for sel in [
        'a[href*="/people/"]',
        'a:has-text("People")',
        'a:has-text("Employees")',
        'a:has-text("Çalışan")',
        'a:has-text("Calisan")',
    ]:
        try:
            candidate = page.query_selector(sel)
            if candidate and candidate.is_visible():
                people_link = candidate
                break
        except Exception:
            pass

    if people_link:
        try:
            href = (people_link.get_attribute("href") or "").strip()
        except Exception:
            href = ""

        try:
            people_link.click()
            human_delay(1200, 1800, deadline=deadline)
            if "/people/" in (page.url or "").lower():
                return True
        except Exception:
            pass

        if href and "/people/" in href:
            target = href if href.startswith("http") else f"https://www.linkedin.com{href}"
            goto_with_retries(page, target, deadline, "employee page", minimum_seconds=6)
            human_delay(1200, 1800, deadline=deadline)
            return "/people/" in (page.url or "").lower()

    fallback = company_url.rstrip("/") + "/people/"
    goto_with_retries(page, fallback, deadline, "employee page", minimum_seconds=6)
    human_delay(1200, 1800, deadline=deadline)
    return "/people/" in (page.url or "").lower()


def choose_conversation_topic_if_needed(page, deadline):
    """Selects the first available conversation topic when LinkedIn requires it."""
    selectors = [
        "select",
        'select[name*="topic"]',
        'select[name*="konu"]',
        'div:has-text("Bir konu seçin")',
        'span:has-text("Bir konu seçin")',
        'button:has-text("Bir konu seçin")',
        'input[placeholder*="konu"]',
        'input[placeholder*="Konu"]',
        '[role="combobox"]',
        'button[aria-label*="konu"]',
        'button[aria-label*="Konu"]',
    ]

    trigger = None
    for sel in selectors:
        try:
            candidate = page.query_selector(sel)
            if candidate and candidate.is_visible():
                value = normalize_text(candidate.get_attribute("value") or "")
                text = normalize_text(candidate.inner_text() or "")
                aria = normalize_text(candidate.get_attribute("aria-label") or "")
                tag = normalize_text(candidate.evaluate("el => el.tagName"))
                combined = " ".join(part for part in [value, text, aria] if part)
                if tag == "select" or "konu" in combined or "topic" in combined or "bir konu secin" in combined:
                    trigger = candidate
                    break
        except Exception:
            pass

    if not trigger:
        try:
            for sel in ["div", "span", "button"]:
                for candidate in page.query_selector_all(sel):
                    try:
                        if not candidate.is_visible():
                            continue
                        text = normalize_text(candidate.inner_text())
                        if text == "bir konu secin":
                            trigger = candidate
                            log.info("Matched conversation topic trigger via visible text scan")
                            break
                    except Exception:
                        pass
                if trigger:
                    break
            fallback = page.query_selector('div:has-text("Bir konu seçin")')
            if not fallback:
                fallback = page.query_selector('span:has-text("Bir konu seçin")')
            if not fallback:
                fallback = page.query_selector('button:has-text("Bir konu seçin")')
            if fallback and fallback.is_visible():
                trigger = fallback
                log.info("Using placeholder element as conversation topic trigger")
            elif page.query_selector('div:has-text("Bir konu seçin")'):
                log.info("Conversation topic placeholder exists but trigger was not matched cleanly")
        except Exception:
            pass
        if not trigger:
            return True

    ensure_time_budget(deadline, 3, "choosing conversation topic")

    try:
        try:
            options = trigger.query_selector_all("option")
            for index, option in enumerate(options):
                text = normalize_text(option.inner_text() or "")
                value = (option.get_attribute("value") or "").strip()
                if not text and not value:
                    continue
                if "konu secin" in text or "select" in text and "topic" in text:
                    continue
                trigger.select_option(index=index)
                log.info("Selected conversation topic via native select: %s", text or value)
                return True
        except Exception:
            pass

        trigger.click()
        try:
            trigger.press("ArrowDown")
            human_delay(200, 300, deadline=deadline)
            trigger.press("Enter")
            log.info("Selected conversation topic via keyboard fallback")
            return True
        except Exception:
            pass

        human_delay(400, 700, deadline=deadline)

        for sel in ['[role="option"]', 'li', 'button', 'div[role="button"]']:
            for option in page.query_selector_all(sel):
                try:
                    if not option.is_visible():
                        continue
                    text = normalize_text(option.inner_text())
                    if not text or "konu secin" in text or "topic" in text and "select" in text:
                        continue
                    option.click()
                    log.info("Selected conversation topic: %s", text)
                    return True
                except Exception:
                    pass
    except Exception as exc:
        log.warning("Conversation topic selection failed: %s", exc)

    return False


def save_debug_screenshot(page, name):
    if not DEBUG_SCREENSHOTS_ENABLED:
        return
    try:
        page.screenshot(path=name, full_page=True)
        log.info("Saved debug screenshot: %s", name)
    except Exception as exc:
        log.warning("Could not save debug screenshot %s: %s", name, sanitize_error_text(exc))


def add_linkedin_session_cookie(ctx, token):
    if not token:
        return
    try:
        ctx.add_cookies(
            [
                {
                    "name": "li_at",
                    "value": token,
                    "domain": ".linkedin.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None",
                }
            ]
        )
    except Exception as exc:
        log.warning("Could not seed LinkedIn session cookie into browser context: %s", sanitize_error_text(exc))


def seed_storage_state(ctx, storage_state):
    if not storage_state:
        return

    cookies = storage_state.get("cookies") or []
    if cookies:
        try:
            ctx.add_cookies(cookies)
        except Exception as exc:
            log.warning("Could not seed storage-state cookies into browser context: %s", sanitize_error_text(exc))

    origins = storage_state.get("origins") or []
    for origin_item in origins:
        origin = (origin_item or {}).get("origin")
        local_items = (origin_item or {}).get("localStorage") or []
        if not origin or not local_items:
            continue

        page = None
        try:
            page = ctx.new_page()
            page.goto(origin, timeout=min(12000, NAVIGATION_TIMEOUT_MS), wait_until="commit")
            page.evaluate(
                """(entries) => {
                    for (const entry of entries) {
                        try {
                            window.localStorage.setItem(entry.name, entry.value);
                        } catch (e) {}
                    }
                }""",
                local_items,
            )
        except Exception as exc:
            log.info("Storage-state localStorage seed did not fully complete for %s: %s", mask_url(origin), sanitize_error_text(exc))
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass


def warm_up_linkedin_session(ctx):
    """
    Warm-up disabled: LinkedIn's bot detection causes ERR_TOO_MANY_REDIRECTS on /feed/.
    Cookies are already loaded from storage state; no warm-up is needed.
    """
    pass


STEALTH_SCRIPT = """
// Hide webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
delete navigator.__proto__.webdriver;

// Realistic plugins
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const arr = [
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
      { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
    ];
    arr.item = i => arr[i];
    arr.namedItem = n => arr.find(p => p.name === n) || null;
    arr.refresh = () => {};
    Object.setPrototypeOf(arr, PluginArray.prototype);
    return arr;
  }
});

// Realistic languages
Object.defineProperty(navigator, 'languages', { get: () => ['tr-TR', 'tr', 'en-US', 'en'] });

// Chrome runtime
window.chrome = {
  app: { isInstalled: false },
  runtime: {
    id: undefined,
    connect: () => {},
    sendMessage: () => {},
    onMessage: { addListener: () => {}, removeListener: () => {} },
  },
  loadTimes: () => ({}),
  csi: () => ({}),
};

// Permissions
const originalQuery = window.navigator.permissions ? window.navigator.permissions.query.bind(navigator.permissions) : null;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : originalQuery(parameters);
}

// WebGL vendor/renderer
const getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
  if (parameter === 37445) return 'Intel Inc.';
  if (parameter === 37446) return 'Intel Iris OpenGL Engine';
  return getParam.call(this, parameter);
};

// Hide automation in toString
const nativeToString = Function.prototype.toString;
Function.prototype.toString = function() {
  if (this === Function.prototype.toString) return 'function toString() { [native code] }';
  return nativeToString.call(this);
};
"""


def setup_browser(playwright, token):
    common_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--window-size=1280,800",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-web-security",
        "--allow-running-insecure-content",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-popup-blocking",
        "--ignore-certificate-errors",
        "--lang=tr-TR",
    ]
    context_options = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "locale": "tr-TR",
        "viewport": {"width": 1280, "height": 800},
    }

    headless = os.getenv("LINKEDIN_HEADLESS", "true").strip().lower() not in {"0", "false", "no", "off"}

    if LINKEDIN_PERSISTENT_SESSION:
        profile_dir = ensure_profile_dir()
        ctx = playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=headless,
            args=common_args,
            **context_options,
        )
        close_target = ctx
        log.info("Browser context created from persistent profile: %s (headless=%s)", profile_dir, headless)
    else:
        storage_state_path = LINKEDIN_STORAGE_STATE_PATH if has_storage_state() else None
        browser = playwright.chromium.launch(headless=headless, args=common_args)
        if storage_state_path:
            ctx = browser.new_context(storage_state=storage_state_path, **context_options)
            log.info("Browser context created from storage state: %s", mask_url(storage_state_path))
        else:
            ctx = browser.new_context(**context_options)
            log.info("Browser context created without storage state")
        close_target = browser

    ctx.add_init_script(STEALTH_SCRIPT)
    if token:
        add_linkedin_session_cookie(ctx, token)
    ctx.set_default_timeout(5000)
    ctx.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    warm_up_linkedin_session(ctx)
    return close_target, ctx


def type_and_verify(textarea, message, deadline):
    """Types the message and verifies that LinkedIn captured the content."""
    ensure_time_budget(deadline, 3, "typing the message")
    textarea.click()
    human_delay(300, 600, deadline=deadline)

    # Clear existing content — works for both <textarea> and contenteditable divs
    try:
        textarea.fill("")
    except Exception:
        pass
    try:
        textarea.press("Control+A")
        human_delay(100, 200, deadline=deadline)
        textarea.press("Backspace")
    except Exception:
        pass

    textarea.type(message[:2000], delay=30)
    human_delay(800, 1200, deadline=deadline)

    # Verification: check all possible ways to read back content
    written = ""
    for method in ("input_value", "inner_text", "text_content"):
        try:
            val = getattr(textarea, method)()
            if val and len(val.strip()) > 5:
                written = val
                break
        except Exception:
            pass

    # Also try JS-based evaluation for contenteditable divs
    if not written:
        try:
            val = textarea.evaluate("el => el.value || el.innerText || el.textContent || ''")
            if val and len(val.strip()) > 5:
                written = val
        except Exception:
            pass

    if not written:
        # Last resort: if the box is still visible and focused, assume typing worked
        try:
            if textarea.is_visible():
                log.warning("type_and_verify: could not confirm content — proceeding optimistically")
                return True
        except Exception:
            pass

    return len((written or "").strip()) > 5


def click_send_button(page, textarea, deadline):
    """Finds the send button and clicks it. Ctrl+Enter is tried first as it is the most reliable."""
    # Ctrl+Enter is the most reliable send method for LinkedIn's composer
    try:
        textarea.press("Control+Return")
        log.info("Sent message via Ctrl+Enter")
        human_delay(600, 900, deadline=deadline)
        return True
    except Exception as exc:
        log.info("Ctrl+Enter failed: %s — falling back to send button search", exc)

    # Fallback: find a dedicated send/submit button near the message form
    send_selectors = [
        ".msg-form__send-button",
        'button[type="submit"]',
        'button.msg-form__send-button',
        '.msg-overlay-conversation-bubble button[type="submit"]',
    ]
    for sel in send_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                log.info("Clicked send button via selector: %s", sel)
                return True
        except Exception:
            pass

    # Final fallback: text/aria token matching (broader search)
    for _ in range(4):
        if time_left(deadline) < 1.5:
            return False
        human_delay(500, 800, deadline=deadline)
        try:
            btn = find_clickable_by_tokens(
                page,
                include_tokens=["mesaj gonder", "send message"],
                exclude_tokens=["gonderi", "paylas", "share"],
            )
            if btn:
                if not btn.is_enabled():
                    continue
                btn.click()
                log.info("Clicked send button via text/aria match")
                return True
        except Exception:
            pass

    return False


def send_via_company_page(page, message, deadline):
    """Uses the company page message button if available."""
    ensure_time_budget(deadline, 6, "company page messaging")
    message_buttons = get_company_message_button_candidates(page)
    if not message_buttons:
        fallback_button = find_company_message_button(page)
        if fallback_button:
            message_buttons = [fallback_button]
    if not message_buttons:
        menu_button = find_company_message_button_via_more_menu(page, deadline)
        if menu_button:
            message_buttons = [menu_button]

    if not message_buttons:
        return None, "No message button on the company page"

    activated = False
    for index, msg_btn in enumerate(message_buttons[:3], start=1):
        try:
            msg_btn.scroll_into_view_if_needed()
        except Exception:
            pass
        if activate_message_ui(page, msg_btn, deadline):
            activated = True
            log.info("Company message UI activated with button candidate %s", index)
            break
        if is_share_overlay(page):
            close_overlay_if_needed(page, deadline)

    if not activated:
        save_debug_screenshot(page, "debug_message_button_click_failed.png")
        return None, "Message surface did not appear after clicking the button"

    textarea = wait_for_message_dialog(page, deadline)

    if not textarea:
        save_debug_screenshot(page, "debug_message_dialog_missing.png")
        return None, "Message dialog did not open"

    # Topic selection is optional — failure here doesn't always block sending
    topic_ok = choose_conversation_topic_if_needed(page, deadline)
    if not topic_ok:
        log.info("Conversation topic selection returned False — proceeding anyway (topic may not be required)")

    if not type_and_verify(textarea, message, deadline):
        save_debug_screenshot(page, "debug_message_type_failed.png")
        return None, "Message could not be typed"

    # Ensure the textarea still exists after typing (LinkedIn sometimes re-renders)
    try:
        if not textarea.is_visible():
            textarea = find_message_input(page) or textarea
    except Exception:
        pass

    if not click_send_button(page, textarea, deadline):
        # Try choosing a topic (in case it became required after typing) and retry send
        choose_conversation_topic_if_needed(page, deadline)
        if not click_send_button(page, textarea, deadline):
            save_debug_screenshot(page, "debug_send_button_failed.png")
            return None, "Send action could not be completed"

    human_delay(1000, 1500, deadline=deadline)
    try:
        if textarea.is_visible():
            log.warning("Dialog is still open after send attempt")
    except Exception:
        pass

    return True, "Message sent from company page"


def send_via_employee(page, company_url, message, deadline):
    """Looks for a reachable employee and tries to send the message there."""
    ensure_time_budget(deadline, 8, "employee search")
    employees_url = company_url.rstrip("/") + "/people/"
    goto_with_retries(page, employees_url, deadline, "employee page", minimum_seconds=8)
    human_delay(1500, 2200, deadline=deadline)
    company_name_hint = derive_company_name(company_url)

    if page_has_rate_limit(page):
        return None, "LinkedIn rate limited on employee page"
    if page_has_auth_wall(page):
        return None, "LinkedIn auth wall on employee page"
    if not ensure_people_page(page, company_url, deadline):
        return None, "People page could not be opened"

    seen = set()
    candidates = []

    for _ in range(4):
        try:
            hrefs = page.eval_on_selector_all(
                "a[href*='/in/']",
                "els => els.map(el => el.getAttribute('href')).filter(Boolean)",
            )
        except Exception:
            hrefs = []

        for href in hrefs:
            if "/in/" not in href:
                continue
            base = href.split("?")[0]
            clean = "https://www.linkedin.com" + base if base.startswith("/") else base
            if clean in seen:
                continue
            seen.add(clean)
            candidates.append(clean)
            if len(candidates) >= MAX_EMPLOYEE_CANDIDATES:
                break

        if candidates:
            break

        try:
            page.mouse.wheel(0, 1800)
        except Exception:
            pass
        human_delay(1100, 1700, deadline=deadline)

    if not candidates:
        try:
            candidates = resolve_people_via_search(page, company_name_hint, deadline)
        except Exception as exc:
            return None, f"No employee candidates found and people search failed: {exc}"

    if not candidates:
        return None, "No employee candidates found"

    for person_url in candidates:
        if time_left(deadline) < 8:
            return None, "Not enough time left for employee retries"

        goto_with_retries(page, person_url, deadline, "employee profile", minimum_seconds=6)
        human_delay(1500, 2200, deadline=deadline)

        msg_btn = find_clickable_by_tokens(
            page,
            include_tokens=["mesaj", "message"],
            exclude_tokens=["mesaj gonder", "send message", "olustur", "compose"],
        )

        if not msg_btn:
            continue

        if not activate_message_ui(page, msg_btn, deadline):
            continue

        textarea = wait_for_message_dialog(page, deadline)

        if not textarea:
            continue

        if not choose_conversation_topic_if_needed(page, deadline):
            continue

        if not type_and_verify(textarea, message, deadline):
            continue

        if click_send_button(page, textarea, deadline):
            return person_url, "Message sent to an employee"

    return None, "Could not send a message to any employee"


def _get_voyager_cookies():
    """Returns (li_at, jsessionid) from storage state + env token."""
    storage = load_storage_state()
    cookies = {c["name"]: c["value"] for c in storage.get("cookies", []) if "name" in c}
    li_at = LINKEDIN_TOKEN or cookies.get("li_at", "")
    jsessionid = cookies.get("JSESSIONID", "")
    return li_at, jsessionid


def send_via_voyager_api(company_url: str, message: str) -> dict:
    """
    Send a LinkedIn connection request with a note using the Voyager internal API.
    No browser automation — pure HTTP with session cookies.
    Connection note is capped at 299 characters by LinkedIn.
    """
    try:
        from linkedin_api import Linkedin  # type: ignore
    except ImportError:
        return {"success": False, "error": "linkedin-api not installed"}

    li_at, jsessionid = _get_voyager_cookies()
    if not li_at:
        return {"success": False, "error": "No li_at token available"}

    slug = unquote((company_url or "").split("/company/")[-1].split("/")[0].strip())
    if not slug:
        return {"success": False, "error": "Could not parse company slug from URL"}

    try:
        api = Linkedin("", "", authenticate=False, cookies={"li_at": li_at, "JSESSIONID": jsessionid})
    except Exception as exc:
        return {"success": False, "error": f"Voyager API init failed: {exc}"}

    company_name = slug.replace("-", " ").title()
    try:
        company_profile = api.get_company(slug)
        if company_profile:
            company_name = company_profile.get("name") or company_name
    except Exception as exc:
        log.warning("Voyager: could not fetch company profile for %s: %s", slug, sanitize_error_text(exc))

    log.info("Voyager: searching employees for %s", mask_company_name(company_name))

    employees = []
    try:
        company_id = None
        if company_profile:
            urn = company_profile.get("entityUrn", "")
            if urn:
                company_id = urn.split(":")[-1]

        if company_id:
            employees = api.search_people(current_company=[company_id], limit=MAX_EMPLOYEE_CANDIDATES + 2) or []
        else:
            employees = api.search_people(keywords=company_name, limit=MAX_EMPLOYEE_CANDIDATES + 2) or []
    except Exception as exc:
        log.warning("Voyager: employee search failed: %s", sanitize_error_text(exc))

    if not employees:
        return {"success": False, "error": "Voyager: no employees found"}

    note = message[:299]  # LinkedIn connection note limit
    sent_to = None
    for person in employees[:MAX_EMPLOYEE_CANDIDATES + 2]:
        urn_id = person.get("urn_id") or person.get("public_id") or ""
        if not urn_id:
            continue
        try:
            result = api.add_connection(urn_id, message=note)
            if result:
                sent_to = urn_id
                log.info("Voyager: connection request sent to %s", urn_id[:6] + "***")
                break
        except Exception as exc:
            log.warning("Voyager: could not send to %s: %s", urn_id[:6] + "***", sanitize_error_text(exc))
            continue

    if sent_to:
        return {
            "success": True,
            "company": company_name,
            "company_url": company_url,
            "method": "voyager_connection_request",
            "person_urn": sent_to,
            "message_sent": note,
        }

    return {"success": False, "error": "Voyager: could not send connection request to any employee"}


def find_and_message_company(company_url: str, message: str, token: str, company_name_hint: str = "") -> dict:
    global _last_request_finished_at
    if not has_linkedin_auth():
        return {"success": False, "error": "LinkedIn auth missing"}
    if "linkedin.com/company" not in company_url:
        return {"success": False, "error": "Not a valid LinkedIn company URL"}

    # --- PRIMARY: Voyager API (no browser, no bot detection) ---
    log.info("Trying Voyager API for %s", mask_url(company_url))
    voyager_result = send_via_voyager_api(company_url, message)
    if voyager_result.get("success"):
        return voyager_result
    log.info("Voyager API failed (%s), falling back to Playwright", voyager_result.get("error"))

    with _lock:
        close_target = None
        normalized_company_url = normalize_linkedin_company_url(company_url)
        company_name = company_name_hint.strip() or derive_company_name(normalized_company_url)
        try:
            deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
            enforce_request_spacing(deadline)
            with sync_playwright() as playwright:
                close_target, ctx = setup_browser(playwright, token)
                page = ctx.new_page()

                log.info("Opening company page: %s", mask_url(normalized_company_url))
                try:
                    normalized_company_url = goto_with_retries(
                        page,
                        normalized_company_url,
                        deadline,
                        "company page",
                        minimum_seconds=10,
                    )
                except Exception as first_exc:
                    fallback_url = resolve_company_page_via_search(page, company_name, deadline)
                    if not fallback_url:
                        raise first_exc
                    normalized_company_url = goto_with_retries(
                        page,
                        fallback_url,
                        deadline,
                        "company page",
                        minimum_seconds=8,
                    )
                human_delay(1500, 2200, deadline=deadline)

                try:
                    h1 = page.query_selector("h1")
                    if h1:
                        company_name = h1.inner_text().strip()
                except Exception:
                    pass

                log.info("Company resolved: %s", mask_company_name(company_name))

                result, info = send_via_company_page(page, message, deadline)
                if result:
                    return {
                        "success": True,
                        "company": company_name,
                        "company_url": normalized_company_url,
                        "method": "company_page",
                        "detail": info,
                        "message_sent": message[:200] + "..." if len(message) > 200 else message,
                    }

                log.info("Company page messaging failed (%s), trying employees", info)
                person_url, info2 = send_via_employee(page, normalized_company_url, message, deadline)
                if person_url:
                    return {
                        "success": True,
                        "company": company_name,
                        "company_url": normalized_company_url,
                        "method": "employee",
                        "person_url": person_url,
                        "detail": info2,
                        "message_sent": message[:200] + "..." if len(message) > 200 else message,
                    }

                return {
                    "success": False,
                    "company": company_name,
                    "error": f"Company page: {info} | Employees: {info2}",
                }

        except TimeoutError as exc:
            log.warning("Message attempt timed out: %s", sanitize_error_text(exc))
            return {"success": False, "company": company_name, "error": str(exc)}
        except Exception as exc:
            log.error("Message attempt failed: %s", sanitize_error_text(exc))
            return {"success": False, "company": company_name, "error": str(exc)}
        finally:
            _last_request_finished_at = time.monotonic()
            if close_target:
                try:
                    close_target.close()
                except Exception:
                    pass


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "linkedin-api",
            "token": bool(LINKEDIN_TOKEN),
            "storage_state": has_storage_state(),
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "navigation_timeout_ms": NAVIGATION_TIMEOUT_MS,
            "max_employee_candidates": MAX_EMPLOYEE_CANDIDATES,
            "persistent_session": LINKEDIN_PERSISTENT_SESSION,
            "profile_dir": LINKEDIN_USER_DATA_DIR if LINKEDIN_PERSISTENT_SESSION else "",
            "storage_state_path": LINKEDIN_STORAGE_STATE_PATH,
        }
    )


@app.route("/send-message", methods=["POST"])
def send_message():
    """Sends a LinkedIn message for one lead."""
    data = request.json or {}
    linkedin_url = data.get("linkedin_url") or data.get("url") or data.get("URL") or ""
    message = data.get("message") or data.get("gonderilecek_mesaj") or data.get("Sales Script") or ""
    company_name = data.get("company_name") or data.get("sirket") or data.get("Sirket") or ""

    if not linkedin_url:
        return jsonify({"success": False, "error": "linkedin_url is required"}), 400
    if not message:
        return jsonify({"success": False, "error": "message is required"}), 400
    if not has_linkedin_auth():
        return jsonify({"success": False, "error": "LinkedIn auth is missing"}), 500

    log.info("POST /send-message -> %s", mask_url(linkedin_url))
    result = find_and_message_company(linkedin_url, message, LINKEDIN_TOKEN, company_name_hint=company_name)
    status = 200 if result.get("success") else 500
    return jsonify(result), status


def build_batch_lead_context(lead, index):
    return {
        "source_index": lead.get("source_index", index),
        "sirket": lead.get("sirket") or lead.get("company_name") or lead.get("Sirket") or "",
        "skor": lead.get("skor", lead.get("score", lead.get("Skor", 0))),
        "website": lead.get("website") or lead.get("Website") or "",
        "linkedin_url": lead.get("linkedin_url") or lead.get("LinkedIn URL") or lead.get("URL") or "",
        "lead_url": lead.get("lead_url") or lead.get("URL") or lead.get("website") or "",
        "mesaj": lead.get("mesaj") or lead.get("message") or lead.get("Sales Script") or lead.get("gonderilecek_mesaj") or "",
        "kaynak": lead.get("kaynak") or lead.get("Kaynak") or "",
        "detayli_analiz": lead.get("detayli_analiz") or lead.get("analysis") or lead.get("Detaylı Analiz") or "",
        "lead_type": lead.get("lead_type") or ("linkedin_ready" if (lead.get("linkedin_url") or lead.get("LinkedIn URL")) else "web_only"),
    }


@app.route("/send-batch", methods=["POST"])
def send_batch():
    """Sends LinkedIn messages for a batch of leads."""
    leads = request.json or []
    if not isinstance(leads, list):
        leads = [leads]

    results = []
    for i, lead in enumerate(leads):
        url = lead.get("URL") or lead.get("linkedin_url") or lead.get("website") or ""
        msg = lead.get("Sales Script") or lead.get("message") or lead.get("gonderilecek_mesaj") or ""
        company_name = lead.get("company_name") or lead.get("sirket") or lead.get("Sirket") or ""
        base_context = build_batch_lead_context(lead, i)

        if "linkedin.com/company" not in url:
            results.append(
                {
                    **base_context,
                    "company": company_name or lead.get("Sirket", "?"),
                    "success": False,
                    "error": "Not a LinkedIn company URL",
                }
            )
            continue

        log.info("Batch [%s/%s]: %s", i + 1, len(leads), mask_url(url))
        result = find_and_message_company(url, msg, LINKEDIN_TOKEN, company_name_hint=company_name)
        results.append({**base_context, **result})

        if i < len(leads) - 1:
            wait = random.uniform(4, 8)
            log.info("Waiting %.1fs before the next company", wait)
            time.sleep(wait)

    success_count = sum(1 for item in results if item.get("success"))
    return jsonify(
        {
            "results": results,
            "total": len(results),
            "success_count": success_count,
            "fail_count": len(results) - success_count,
        }
    )


if __name__ == "__main__":
    log.info("Starting LinkedIn API - token: %s", "present" if LINKEDIN_TOKEN else "missing")
    app.run(host="0.0.0.0", port=8502, debug=False)
