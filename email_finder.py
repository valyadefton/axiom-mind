"""
email_finder.py — честный поиск email по домену компании (бесплатно).

Главный принцип: возвращаем ТОЛЬКО адреса, которые реально найдены в источнике.
Ничего не угадываем и не подставляем. Не нашли — пустой список ("email not found").

Как это работает:
1. Открываем ТОЛЬКО главную страницу сайта компании (https://domain, www.domain, http://domain —
   пробуем по очереди, первая успешная и используется). Страницы "Контакты"/"О нас" не открываем —
   это и есть источник задержки в 60+ секунд на 5 доменов, которого просили избежать.
2. Достаём адреса: из ссылок mailto:, из текста страницы, из защиты Cloudflare (data-cfemail),
   из записей вида "info [at] site.ru".
3. Выбрасываем мусор: картинки (logo@2x.png), заглушки (example.com), адреса из одних цифр
   (как тот самый "22@sm-stomatology.ru"), noreply, чужие домены (адрес веб-студии в подвале).
4. Каждый найденный адрес проверяем через email_verify (MX + SMTP). "invalid" — выбрасываем.
5. (Опционально) Если на главной странице ничего нет — спрашиваем Hunter.io (нужен HUNTER_API_KEY,
   бесплатный тариф очень ограничен, поэтому по умолчанию выключено).

Компромисс: часть компаний публикует email только на отдельной странице "Контакты", а не на
главной. Для них теперь будет "email not found" там, где раньше находился адрес. Это осознанный
обмен полноты на скорость — see use_hunter, если для таких доменов нужен запасной источник.

Статусы email_status в результате:
    verified    — сервер подтвердил ящик
    risky       — домен catch-all (принимает любые адреса)
    unverified  — адрес опубликован на сайте компании, но проверить SMTP не удалось
                  (например, закрыт порт 25)

Ограничения (честно):
- Сайты, которые рисуются целиком через JavaScript, и сайты, где почта спрятана за формой,
  дадут "не найдено" — и это правильный результат.
- Чаще всего на сайтах публикуют общие ящики (info@, office@), а не почту директора.
"""

import asyncio
import html
import logging
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import httpx

from email_verify import ROLE_LOCALS, verify_email_address

logger = logging.getLogger("axiom_mind.finder")

PAGE_TIMEOUT = 10.0            # секунд на загрузку главной страницы
MAX_PAGE_CHARS = 1_500_000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AxiomMindBot/1.0)",
    "Accept-Language": "en,ru;q=0.8",
}

# Каталоги, соцсети, агрегаторы: их почта — не почта компании
BLOCKED_DOMAINS = {
    "google.com", "yandex.ru", "ya.ru", "2gis.ru", "2gis.com", "zoon.ru", "prodoctorov.ru",
    "yell.ru", "flamp.ru", "facebook.com", "instagram.com", "vk.com", "ok.ru", "t.me",
    "linkedin.com", "youtube.com", "twitter.com", "x.com", "wikipedia.org", "yelp.com",
    "tripadvisor.com", "tripadvisor.ru", "avito.ru", "hh.ru", "yellowpages.com",
    "mapquest.com", "bbb.org", "crunchbase.com", "zoominfo.com", "clutch.co", "glassdoor.com",
}

# Бесплатные почтовики: принимаем, только если адрес найден на сайте самой компании
FREEMAIL = {
    "gmail.com", "yandex.ru", "yandex.com", "ya.ru", "mail.ru", "bk.ru", "inbox.ru",
    "list.ru", "internet.ru", "rambler.ru", "outlook.com", "hotmail.com", "yahoo.com",
    "icloud.com", "proton.me", "protonmail.com",
}

JUNK_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "woff", "woff2", "ico", "pdf", "map"}
PLACEHOLDER_DOMAINS = {
    "example.com", "domain.com", "email.com", "yourdomain.com", "site.com", "mysite.com",
    "test.com", "sentry.io", "wixpress.com",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.[a-zA-Z]{2,}")


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
def normalize_domain(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0].split("?")[0].split(":")[0]
    return value[4:] if value.startswith("www.") else value


def _same_domain(a: str, b: str) -> bool:
    """a и b — один домен или поддомен друг друга."""
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _is_blocked(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in BLOCKED_DOMAINS)


def _is_junk(email: str) -> bool:
    local, domain = email.rsplit("@", 1)
    tld = domain.rsplit(".", 1)[-1]
    if tld in JUNK_TLDS:
        return True
    if domain in PLACEHOLDER_DOMAINS or domain.endswith(".sentry.io") or domain.endswith(".wixpress.com"):
        return True
    if len(local) < 2 or not re.search(r"[a-z]", local):  # "22", "1", "123"
        return True
    if local.startswith(("noreply", "no-reply", "donotreply", "do-not-reply")):
        return True
    return False


def _deobfuscate(text: str) -> str:
    text = re.sub(r"\s*[\[\(\{]\s*(?:at|собака)\s*[\]\)\}]\s*", "@", text, flags=re.I)
    text = re.sub(r"\s*[\[\(\{]\s*(?:dot|точка)\s*[\]\)\}]\s*", ".", text, flags=re.I)
    return text


def _decode_cfemail(hex_string: str) -> str:
    """Cloudflare прячет email в hex: первый байт — ключ XOR для остальных."""
    try:
        key = int(hex_string[:2], 16)
        return "".join(
            chr(int(hex_string[i:i + 2], 16) ^ key) for i in range(2, len(hex_string), 2)
        )
    except ValueError:
        return ""


def extract_emails(page: str) -> Dict[str, bool]:
    """Возвращает {email: найден_ли_в_mailto}."""
    found: Dict[str, bool] = {}
    text = html.unescape(page)

    for hex_string in re.findall(r'data-cfemail=["\']([0-9a-fA-F]+)["\']', text):
        decoded = _decode_cfemail(hex_string).lower()
        for e in EMAIL_RE.findall(decoded):
            found[e] = True

    for href in re.findall(r'mailto:([^"\'\s>]+)', text, flags=re.I):
        for e in EMAIL_RE.findall(unquote(href)):
            found[e.lower()] = True

    visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    visible = re.sub(r"<[^>]+>", " ", _deobfuscate(visible))
    for e in EMAIL_RE.findall(visible):
        found.setdefault(e.lower(), False)

    return found


async def _fetch(client: httpx.AsyncClient, url: str) -> Optional[Tuple[str, str]]:
    """Возвращает (html, итоговый_url) или None."""
    try:
        resp = await client.get(url, headers=HEADERS, timeout=PAGE_TIMEOUT, follow_redirects=True)
        if resp.status_code >= 400:
            return None
        ctype = resp.headers.get("content-type", "")
        if ctype and "html" not in ctype and "text" not in ctype:
            return None
        return resp.text[:MAX_PAGE_CHARS], str(resp.url)
    except Exception as e:
        logger.debug(f"fetch failed {url}: {e}")
        return None


async def _fetch_home(client: httpx.AsyncClient, domain: str) -> Optional[Tuple[str, str]]:
    for url in (f"https://{domain}", f"https://www.{domain}", f"http://{domain}"):
        result = await _fetch(client, url)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# Hunter.io (опционально)
# ---------------------------------------------------------------------------
async def _hunter_domain_search(client: httpx.AsyncClient, domain: str, limit: int) -> List[Dict]:
    api_key = os.environ.get("HUNTER_API_KEY", "")  # читаем здесь, чтобы .env уже был загружен
    if not api_key:
        return []
    try:
        resp = await client.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "limit": limit},
            headers={"X-API-KEY": api_key},
            timeout=20.0,
        )
        if resp.status_code != 200:
            logger.warning(f"Hunter.io {domain}: HTTP {resp.status_code}")
            return []
        data = resp.json().get("data", {}) or {}
    except Exception as e:
        logger.warning(f"Hunter.io error for {domain}: {e}")
        return []

    contacts: List[Dict] = []
    for item in data.get("emails", []) or []:
        address = (item.get("value") or "").strip().lower()
        status = (item.get("verification") or {}).get("status")
        if not address or _is_junk(address) or status == "invalid":
            continue
        if (item.get("confidence") or 0) < 70:
            continue
        name = " ".join(p for p in (item.get("first_name"), item.get("last_name")) if p) or "—"
        contacts.append({
            "full_name": name,
            "position": item.get("position") or "—",
            "email": address,
            "email_status": {"valid": "verified", "accept_all": "risky"}.get(status, "unverified"),
            "linkedin_url": item.get("linkedin"),
            "source": "hunter.io",
        })
    return contacts[:limit]


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------
async def find_emails_for_domain(
    client: httpx.AsyncClient,
    domain_or_url: str,
    limit: int = 5,
    verify: bool = True,
    use_hunter: bool = False,
) -> List[Dict]:
    """
    Возвращает список контактов в формате, который уже использует main.py:
    {full_name, position, email, email_status, linkedin_url} (+ source).
    Пустой список = "email not found".
    """
    domain = normalize_domain(domain_or_url)
    if not domain or "." not in domain or _is_blocked(domain):
        return []

    results: List[Dict] = []

    home = await _fetch_home(client, domain)
    if home:
        home_html, base_url = home

        candidates: Dict[str, Dict] = {}
        for email, via_mailto in extract_emails(home_html).items():
            if _is_junk(email):
                continue
            email_domain = email.rsplit("@", 1)[1]
            same = _same_domain(email_domain, domain)
            if not (same or email_domain in FREEMAIL):
                continue  # чужой домен (веб-студия, партнёр) — не почта компании
            candidates[email] = {"email": email, "same_domain": same, "mailto": via_mailto, "source": base_url}

        ranked = sorted(
            candidates.values(),
            key=lambda c: (not c["same_domain"], c["email"].split("@")[0] in ROLE_LOCALS, not c["mailto"]),
        )[:limit]

        async def enrich(c: Dict) -> Optional[Dict]:
            local = c["email"].split("@")[0]
            status = "unverified"
            if verify:
                verdict = await verify_email_address(c["email"])
                if verdict["status"] == "invalid":
                    return None  # опубликован, но ящика нет — не отдаём
                status = {"valid": "verified", "catch_all": "risky"}.get(verdict["status"], "unverified")
            return {
                "full_name": "—",
                "position": "General inbox" if local in ROLE_LOCALS else "—",
                "email": c["email"],
                "email_status": status,
                "linkedin_url": None,
                "source": c["source"],
            }

        enriched = await asyncio.gather(*[enrich(c) for c in ranked])
        results = [r for r in enriched if r]

    if not results and use_hunter:
        results = await _hunter_domain_search(client, domain, limit=min(limit, 3))

    logger.info(f"find_emails {domain}: {len(results)} найдено")
    return results
