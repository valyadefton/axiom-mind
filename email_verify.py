"""
email_verify.py — проверка, существует ли email-ящик, без платных сервисов.

Как это работает (по шагам):
1. Проверяем синтаксис адреса.
2. Ищем MX-записи домена (DNS): кому этот домен доставляет почту.
3. Подключаемся к почтовому серверу по SMTP (порт 25) и делаем "репетицию" отправки:
   MAIL FROM -> RCPT TO <адрес>. Письмо НЕ отправляется — мы только смотрим,
   скажет ли сервер "такой ящик есть" (250) или "нет такого" (550).
4. Проверка catch-all: спрашиваем заведомо несуществующий адрес на том же домене.
   Если сервер и его "принимает" — домен отвечает "да" на всё, и результату верить нельзя.

Статусы:
    valid      — сервер подтвердил ящик, домен не catch-all
    invalid    — ящика/домена нет
    catch_all  — домен принимает любые адреса, существование ящика не проверить (risky)
    unknown    — проверить не удалось (порт 25 закрыт, greylisting, таймаут, блокировка)

ВАЖНО: многие домашние провайдеры блокируют исходящий порт 25.
Тогда всё будет "unknown / smtp_unreachable" — это не баг кода.
"""

import asyncio
import logging
import os
import random
import re
import smtplib
import string
from typing import Dict, List

import dns.exception
import dns.resolver

logger = logging.getLogger("axiom_mind.verify")

# Настройки (можно переопределить в .env: VERIFY_HELO_HOST, VERIFY_MAIL_FROM).
# Читаются в момент вызова, а не при импорте: load_dotenv() в main.py срабатывает позже импортов.
SMTP_PORT = 25
SMTP_TIMEOUT = 3  # секунд на подключение и на каждую SMTP-команду

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Ролевые адреса: ящик существует, но это не конкретный человек
ROLE_LOCALS = {
    "info", "admin", "office", "contact", "sales", "support", "hello",
    "mail", "help", "service", "team", "hr", "marketing", "noreply", "no-reply",
}

# Слова в ответе сервера, которые означают "вас заблокировали", а не "ящика нет"
POLICY_HINTS = ("spam", "block", "blacklist", "denied", "policy", "reputation", "spamhaus", "banned")

# Кэш: домен -> catch-all или нет (чтобы не спрашивать сервер дважды)
_catch_all_cache: Dict[str, bool] = {}

# Не больше 10 одновременных SMTP-проверок
_SEM = asyncio.Semaphore(10)


def _resolve_mx(domain: str) -> List[str]:
    """
    Возвращает список MX-серверов (по приоритету). Пустой список = домена/почты нет.
    Другие DNS-ошибки (таймаут и т.п.) пробрасываются наверх — это "unknown", не "invalid".
    """
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 8
    try:
        answers = resolver.resolve(domain, "MX")
        records = sorted(answers, key=lambda r: r.preference)
        return [str(r.exchange).rstrip(".") for r in records]
    except dns.resolver.NXDOMAIN:
        return []
    except dns.resolver.NoAnswer:
        # По стандарту, если MX нет, почта идёт на A-запись домена
        try:
            resolver.resolve(domain, "A")
            return [domain]
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []


def _smtp_probe(mx_host: str, email: str, check_catch_all: bool) -> Dict:
    """
    Блокирующая SMTP-проверка (запускается в отдельном потоке).
    Возвращает: {"code": int, "message": str, "catch_all": bool|None, "stage": str}
    """
    domain = email.rsplit("@", 1)[1]
    server = smtplib.SMTP(timeout=SMTP_TIMEOUT)  # без хоста — пока не подключается
    try:
        server.connect(mx_host, SMTP_PORT)
        server.ehlo(os.environ.get("VERIFY_HELO_HOST", "localhost"))

        code, msg = server.mail(os.environ.get("VERIFY_MAIL_FROM", "verify@example.com"))
        if code >= 400:
            return {"code": code, "message": msg.decode(errors="replace")[:200],
                    "catch_all": None, "stage": "mail_from"}

        code, msg = server.rcpt(email)
        result = {"code": code, "message": msg.decode(errors="replace")[:200],
                  "catch_all": None, "stage": "rcpt"}

        # Проверка catch-all: случайный адрес, которого точно не существует
        if code in (250, 251) and check_catch_all:
            random_local = "zz" + "".join(random.choices(string.ascii_lowercase + string.digits, k=14))
            fake_code, _ = server.rcpt(f"{random_local}@{domain}")
            result["catch_all"] = fake_code in (250, 251)

        return result
    finally:
        try:
            server.quit()
        except Exception:
            pass  # соединение могло уже закрыться — это нормально


async def verify_email_address(email: str) -> Dict:
    email = (email or "").strip().lower()
    result: Dict = {
        "email": email,
        "status": "unknown",
        "reason": "",
        "is_role": False,
        "is_catch_all": None,
        "mx": None,
        "smtp_code": None,
    }

    # 1. Синтаксис
    if not EMAIL_RE.match(email):
        result.update(status="invalid", reason="bad_syntax")
        return result

    local, domain = email.rsplit("@", 1)
    result["is_role"] = local in ROLE_LOCALS

    # 2. MX-записи
    try:
        mx_list = await asyncio.to_thread(_resolve_mx, domain)
    except dns.exception.DNSException as e:
        result.update(status="unknown", reason=f"dns_error: {type(e).__name__}")
        return result

    if not mx_list:
        result.update(status="invalid", reason="domain_has_no_mail_server")
        return result
    result["mx"] = mx_list[0]

    # 3. SMTP-проверка
    cached = _catch_all_cache.get(domain)
    try:
        async with _SEM:
            probe = await asyncio.to_thread(_smtp_probe, mx_list[0], email, cached is None)
    except (OSError, smtplib.SMTPException) as e:
        # Самая частая причина: провайдер блокирует порт 25
        result.update(status="unknown", reason=f"smtp_unreachable: {type(e).__name__}")
        return result

    code = probe["code"]
    message = (probe.get("message") or "").lower()
    result["smtp_code"] = code

    if probe.get("stage") == "mail_from":
        # Сервер не принял НАШ адрес отправителя — про ящик получателя ничего не узнали
        result.update(status="unknown", reason="sender_rejected_by_server")
        return result

    if code in (250, 251):
        if probe["catch_all"] is not None:
            _catch_all_cache[domain] = probe["catch_all"]
        is_catch_all = _catch_all_cache.get(domain, False)
        result["is_catch_all"] = is_catch_all
        if is_catch_all:
            result.update(status="catch_all", reason="domain_accepts_any_address")
        else:
            result.update(status="valid", reason="mailbox_exists")
    elif code in (550, 551, 553, 554):
        if any(h in message for h in POLICY_HINTS):
            result.update(status="unknown", reason="rejected_by_server_policy")
        else:
            result.update(status="invalid", reason="mailbox_does_not_exist")
    elif 400 <= code < 500:
        result.update(status="unknown", reason="temporary_failure_or_greylisting")
    else:
        result.update(status="unknown", reason=f"unexpected_smtp_code_{code}")

    logger.info(f"verify {email}: {result['status']} ({result['reason']})")
    return result
