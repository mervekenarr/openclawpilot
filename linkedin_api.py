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
import os
import random
import threading
import time


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("linkedin-api")

app = Flask(__name__)

LINKEDIN_TOKEN = os.getenv("LINKEDIN_SESSION_TOKEN", "")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("LINKEDIN_REQUEST_TIMEOUT", "85"))
NAVIGATION_TIMEOUT_MS = int(os.getenv("LINKEDIN_NAV_TIMEOUT_MS", "20000"))
MAX_EMPLOYEE_CANDIDATES = int(os.getenv("LINKEDIN_MAX_EMPLOYEE_CANDIDATES", "2"))

_lock = threading.Lock()


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
            trigger.select_option(index=1)
            log.info("Selected conversation topic via native select")
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
    try:
        page.screenshot(path=name, full_page=True)
        log.info("Saved debug screenshot: %s", name)
    except Exception as exc:
        log.warning("Could not save debug screenshot %s: %s", name, exc)


def setup_browser(playwright, token):
    browser = playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="tr-TR",
        viewport={"width": 1280, "height": 800},
    )
    ctx.add_cookies(
        [
            {
                "name": "li_at",
                "value": token,
                "domain": ".linkedin.com",
                "path": "/",
            }
        ]
    )
    ctx.set_default_timeout(5000)
    ctx.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    return browser, ctx


def type_and_verify(textarea, message, deadline):
    """Types the message and verifies that LinkedIn captured the content."""
    ensure_time_budget(deadline, 3, "typing the message")
    textarea.click()
    human_delay(300, 600, deadline=deadline)
    textarea.type(message[:2000], delay=30)
    human_delay(800, 1200, deadline=deadline)

    written = None
    try:
        written = textarea.input_value()
    except Exception:
        written = None

    if not written:
        try:
            written = textarea.inner_text()
        except Exception:
            written = ""

    return len((written or "").strip()) > 5


def click_send_button(page, textarea, deadline):
    """Finds the send button and clicks it, with Ctrl+Enter fallback."""
    for _ in range(4):
        if time_left(deadline) < 1.5:
            return False
        human_delay(500, 900, deadline=deadline)
        try:
            for btn in page.query_selector_all("button"):
                if not btn or not btn.is_visible() or not btn.is_enabled():
                    continue
                text = normalize_text(btn.inner_text())
                aria = normalize_text(btn.get_attribute("aria-label") or "")
                title = normalize_text(btn.get_attribute("title") or "")
                combined = " ".join(part for part in [text, aria, title] if part)
                if any(
                    token in combined
                    for token in ["gonder", "mesaj gonder", "send", "send message"]
                ):
                    btn.click()
                    log.info("Clicked send button via text/aria match: %s", combined)
                    return True
        except Exception:
            pass

    log.info("Send button not found, trying Ctrl+Enter")
    try:
        textarea.press("Control+Return")
        return True
    except Exception:
        return False


def send_via_company_page(page, message, deadline):
    """Uses the company page message button if available."""
    ensure_time_budget(deadline, 6, "company page messaging")
    msg_btn = None

    for sel in ['button:has-text("Mesaj")', 'button:has-text("Message")']:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                aria = (btn.get_attribute("aria-label") or "").lower()
                text = btn.inner_text().strip().lower()
                if text in ("mesaj", "message") and "olustur" not in aria and "compose" not in aria:
                    msg_btn = btn
                    break
        except Exception:
            pass

    if not msg_btn:
        return None, "No message button on the company page"

    msg_btn.click()
    log.info("Clicked company message button")

    textarea = None
    for _ in range(5):
        if time_left(deadline) < 2:
            return None, "Not enough time left to open the message dialog"
        human_delay(800, 1100, deadline=deadline)
        for sel in [
            'textarea[placeholder*="mesaj"]',
            'textarea[placeholder*="Mesaj"]',
            'textarea[placeholder*="message"]',
            'textarea[placeholder*="Message"]',
            'div[role="textbox"]',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    textarea = el
                    break
            except Exception:
                pass
        if textarea:
            break

    if not textarea:
        save_debug_screenshot(page, "debug_message_dialog_missing.png")
        return None, "Message dialog did not open"

    if not choose_conversation_topic_if_needed(page, deadline):
        save_debug_screenshot(page, "debug_topic_selection_failed.png")
        return None, "Conversation topic could not be selected"

    if not type_and_verify(textarea, message, deadline):
        save_debug_screenshot(page, "debug_message_type_failed.png")
        return None, "Message could not be typed"

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
    page.goto(employees_url, timeout=min(NAVIGATION_TIMEOUT_MS, 15000))
    human_delay(1500, 2200, deadline=deadline)

    cards = page.query_selector_all("a[href*='/in/']")
    seen = set()
    candidates = []

    for card in cards:
        href = card.get_attribute("href") or ""
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

    if not candidates:
        return None, "No employee candidates found"

    for person_url in candidates:
        if time_left(deadline) < 8:
            return None, "Not enough time left for employee retries"

        page.goto(person_url, timeout=min(NAVIGATION_TIMEOUT_MS, 12000))
        human_delay(1500, 2200, deadline=deadline)

        msg_btn = None
        for sel in ['button:has-text("Mesaj")', 'button:has-text("Message")']:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    msg_btn = btn
                    break
            except Exception:
                pass

        if not msg_btn:
            continue

        msg_btn.click()
        human_delay(900, 1400, deadline=deadline)

        textarea = None
        for sel in [
            'textarea[placeholder*="mesaj"]',
            'textarea[placeholder*="message"]',
            'textarea',
            'div[role="textbox"]',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    textarea = el
                    break
            except Exception:
                pass

        if not textarea:
            continue

        if not choose_conversation_topic_if_needed(page, deadline):
            continue

        if not type_and_verify(textarea, message, deadline):
            continue

        if click_send_button(page, textarea, deadline):
            return person_url, "Message sent to an employee"

    return None, "Could not send a message to any employee"


def find_and_message_company(company_url: str, message: str, token: str) -> dict:
    if not token:
        return {"success": False, "error": "LinkedIn token missing"}
    if "linkedin.com/company" not in company_url:
        return {"success": False, "error": "Not a valid LinkedIn company URL"}

    with _lock:
        browser = None
        try:
            deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
            with sync_playwright() as playwright:
                browser, ctx = setup_browser(playwright, token)
                page = ctx.new_page()

                log.info("Opening company page: %s", company_url)
                page.goto(company_url, timeout=NAVIGATION_TIMEOUT_MS)
                human_delay(1500, 2200, deadline=deadline)

                company_name = company_url.split("/company/")[-1].strip("/").replace("-", " ").title()
                try:
                    h1 = page.query_selector("h1")
                    if h1:
                        company_name = h1.inner_text().strip()
                except Exception:
                    pass

                log.info("Company resolved: %s", company_name)

                result, info = send_via_company_page(page, message, deadline)
                if result:
                    return {
                        "success": True,
                        "company": company_name,
                        "company_url": company_url,
                        "method": "company_page",
                        "detail": info,
                        "message_sent": message[:200] + "..." if len(message) > 200 else message,
                    }

                log.info("Company page messaging failed (%s), trying employees", info)
                person_url, info2 = send_via_employee(page, company_url, message, deadline)
                if person_url:
                    return {
                        "success": True,
                        "company": company_name,
                        "company_url": company_url,
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
            log.warning("Message attempt timed out: %s", exc)
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            log.error("Message attempt failed: %s", exc)
            return {"success": False, "error": str(exc)}
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "linkedin-api",
            "token": bool(LINKEDIN_TOKEN),
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "navigation_timeout_ms": NAVIGATION_TIMEOUT_MS,
            "max_employee_candidates": MAX_EMPLOYEE_CANDIDATES,
        }
    )


@app.route("/send-message", methods=["POST"])
def send_message():
    """Sends a LinkedIn message for one lead."""
    data = request.json or {}
    linkedin_url = data.get("linkedin_url") or data.get("url") or data.get("URL") or ""
    message = data.get("message") or data.get("gonderilecek_mesaj") or data.get("Sales Script") or ""

    if not linkedin_url:
        return jsonify({"success": False, "error": "linkedin_url is required"}), 400
    if not message:
        return jsonify({"success": False, "error": "message is required"}), 400
    if not LINKEDIN_TOKEN:
        return jsonify({"success": False, "error": "LINKEDIN_SESSION_TOKEN is missing"}), 500

    log.info("POST /send-message -> %s", linkedin_url)
    result = find_and_message_company(linkedin_url, message, LINKEDIN_TOKEN)
    status = 200 if result.get("success") else 500
    return jsonify(result), status


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

        if "linkedin.com/company" not in url:
            results.append(
                {
                    "company": lead.get("Sirket", "?"),
                    "success": False,
                    "error": "Not a LinkedIn company URL",
                }
            )
            continue

        log.info("Batch [%s/%s]: %s", i + 1, len(leads), url)
        result = find_and_message_company(url, msg, LINKEDIN_TOKEN)
        results.append(result)

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
