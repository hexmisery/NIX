import asyncio
from dataclasses import replace
import html
import json
import re
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit

import aiohttp

from .models import Result, substitute, username
from .network import Network
from .connections import extract_links
from .evidence import identity_evidence, structured_identity

CHALLENGE = (
    "cf-chl-",
    "cf-turnstile",
    "verify you are human",
    "<title>just a moment",
    "checking your browser",
    "<title>access denied",
    "captcha-container",
)


def classify(rule, account, code, body, final_url, truncated=False):
    lower = body.lower()
    if code in (401, 403, 407, 429, 451, 999) or any(x in lower for x in CHALLENGE):
        return "blocked", "Доступ ограничен, капча или лимит запросов"
    if code >= 500 or code == 0:
        return "error", f"Сайт недоступен: HTTP {code}"
    if rule.absent and any(
        x.replace("{username}", account).replace("{account}", account) in body
        for x in rule.absent
    ):
        return "missing", "Найден признак отсутствия профиля"
    if code == rule.missing_code and code != rule.exists_code:
        return "missing", f"HTTP {code}: код отсутствия из правила"
    if code in (404, 410) and rule.exists_code not in (404, 410):
        return "missing", f"HTTP {code}"
    p = urlsplit(final_url)
    probe = urlsplit(substitute(rule.probe, account))
    if final_url != substitute(rule.probe, account):
        if p.path.rstrip("/") in ("", "/login", "/signin", "/auth", "/search"):
            return "possible", "Перенаправление на главную, поиск или вход"
        if p.hostname != probe.hostname and (p.hostname or "").removeprefix("www.") != (
            probe.hostname or ""
        ).removeprefix("www."):
            return "possible", "Перенаправление на другой домен"
    if truncated:
        return "possible", "Ответ превышает 1 МБ; проверка неполная"
    if rule.kind == "webfinger":
        from .fediverse import webfinger_profile

        return (
            ("found", "WebFinger account confirmed")
            if code == 200
            and webfinger_profile(account, body, substitute(rule.profile, account))
            else ("possible", "WebFinger identity not confirmed")
        )
    if rule.kind == "json_user":
        if code != rule.exists_code:
            return "possible", f"Неожиданный HTTP-код JSON-профиля: {code}"
        try:
            obj = json.loads(body)
            for part in rule.json_path.split(".") if rule.json_path else []:
                obj = obj[part]
            actual = obj.get("username", "")
            identifier = obj.get("id", obj.get("uid"))
            if (
                isinstance(actual, str)
                and actual.casefold() == account.casefold()
                and identifier is not None
            ):
                return "found", "В JSON совпал ник и найден ID профиля"
            return "possible", "JSON не подтвердил точный ник и ID профиля"
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            return "possible", "Вместо ожидаемого JSON пришёл другой ответ"
    if rule.present:
        if code == rule.exists_code and all(
            x.replace("{username}", account).replace("{account}", account) in body
            for x in rule.present
        ):
            return "found", "Совпали признаки профиля из каталога"
        return "possible", "Не совпали все признаки профиля"
    if rule.absent and 200 <= code < 300:
        return "possible", "Нет признака ошибки, но нет положительного признака профиля"
    if code == rule.exists_code:
        return "possible", "Подходящий HTTP-ответ; содержимое требует проверки"
    return "possible", f"Неожиданный ответ: HTTP {code}"


def title_of(body):
    match = re.search(r"<title[^>]*>(.*?)</title>", body[:200000], re.I | re.S)
    return (
        html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()[:180]
        if match
        else ""
    )


async def check_site(net, site, account, verify=True, preview=None):
    rule = site.primary
    start = time.monotonic()
    candidate_identity = False
    result = Result(
        rule.site,
        substitute(rule.profile, account),
        site.sources,
        rule.category,
        "error",
        "",
    )
    try:
        code, body, final, truncated = await net.get(substitute(rule.probe, account))
        result.http = code
        result.title = title_of(body)
        result.status, result.reason = classify(
            rule, account, code, body, final, truncated
        )
        if rule.kind == "webfinger" and result.status == "found":
            from .fediverse import webfinger_profile

            result.url = webfinger_profile(account, body, result.url) or result.url
        probe_url = urlsplit(substitute(rule.probe, account))
        final_url = urlsplit(final)
        valid_location = (
            (final_url.hostname or "").removeprefix("www.")
            == (probe_url.hostname or "").removeprefix("www.")
            and final_url.path.rstrip("/")
            not in ("/login", "/signin", "/auth", "/search")
            and (bool(final_url.path.rstrip("/")) or not probe_url.path.rstrip("/"))
        )
        candidate_identity = (
            result.status in ("found", "possible")
            and not truncated
            and 200 <= code < 300
            and valid_location
            and identity_evidence(rule, account, body, result.url)
        )
        strong_identity = candidate_identity and structured_identity(
            account, body, result.url
        )
        if result.status == "possible" and strong_identity:
            result.status, result.reason = "found", "Profile username and ID confirmed"
        if (
            result.status in ("found", "possible")
            and not truncated
            and 200 <= code < 300
        ):
            result.links = extract_links(body, result.url)
        if verify and candidate_identity:
            if preview:
                preview(
                    replace(
                        result,
                        status="possible",
                        checking=True,
                        reason=result.reason + "; идёт контрольная проверка",
                    )
                )
            control = "na" + secrets.token_hex(10)
            try:
                cc, cb, cf, ct = await net.get(substitute(rule.probe, control))
                cs, _ = classify(rule, control, cc, cb, cf, ct)
                if (cc == code and cb == body and not ct) or (
                    cs == "found"
                    and (
                        not strong_identity
                        or identity_evidence(
                            rule, control, cb, substitute(rule.profile, control)
                        )
                    )
                ):
                    result.status = "possible"
                    result.reason = "Контрольный случайный ник дал такой же признак; возможна заглушка"
                elif cs == "missing":
                    if result.status == "possible" and candidate_identity:
                        result.status = "found"
                        result.reason = "Адрес профиля отвечает; контрольный случайный ник отсутствует"
                    else:
                        result.reason += "; случайный ник отсутствует"
                elif not strong_identity:
                    result.status = "possible"
                    result.reason += "; контрольная проверка неубедительна"
            except aiohttp.ClientConnectorDNSError as exc:
                host = urlsplit(rule.probe).hostname or ""
                missing_dns = getattr(exc.os_error, "errno", None) in (
                    socket.EAI_NONAME,
                    getattr(socket, "EAI_NODATA", socket.EAI_NONAME),
                    11001,
                )
                if (
                    "{username}" in host
                    and missing_dns
                    and identity_evidence(rule, account, body, result.url)
                ):
                    result.status = "found"
                    result.reason = "Profile confirmed; random subdomain absent"
                else:
                    result.status = "possible"
                    result.reason = "Control DNS unavailable"
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
                if not strong_identity:
                    result.status = "possible"
                    result.reason += "; контрольная проверка недоступна"
    except asyncio.TimeoutError:
        result.reason = "Истекло время ожидания"
    except (aiohttp.ClientError, OSError):
        result.reason = "Ошибка соединения, DNS или TLS"
    except ValueError as exc:
        result.reason = str(exc)
    if result.status == "found" and not candidate_identity:
        result.status = "possible"
        result.reason = "Profile identity not confirmed"
    result.verified = result.status == "found"
    result.elapsed = round(time.monotonic() - start, 2)
    return result


async def scan(
    sites,
    account,
    callback,
    cancel: threading.Event,
    concurrency=16,
    verify=True,
    network_factory=Network,
    preview=None,
):
    account = username(account)
    queue = asyncio.Queue()
    for site in sites:
        queue.put_nowait(site)

    async with network_factory(concurrency=concurrency, timeout=8) as net:

        async def worker():
            while not cancel.is_set():
                try:
                    site = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    result = await check_site(net, site, account, verify, preview)
                    if result.status in ("error", "blocked", "possible"):
                        primary_probe = substitute(site.primary.probe, account)
                        alternative = next(
                            (
                                rule
                                for rule in site.rules[1:]
                                if substitute(rule.probe, account) != primary_probe
                            ),
                            None,
                        )
                        if alternative:
                            retry = await check_site(
                                net, type(site)([alternative]), account, verify, preview
                            )
                            if (
                                retry.status == "found"
                                or result.status in ("error", "blocked")
                                and retry.status == "possible"
                            ):
                                retry.url, retry.source = result.url, site.sources
                                result = retry
                except Exception as exc:
                    rule = site.primary
                    result = Result(
                        rule.site,
                        substitute(rule.profile, account),
                        site.sources,
                        rule.category,
                        "error",
                        f"Site response error: {type(exc).__name__}",
                    )
                callback(result)

        tasks = [
            asyncio.create_task(worker()) for _ in range(min(concurrency, len(sites)))
        ]
        if not tasks:
            return
        group = asyncio.gather(*tasks)
        try:
            while not group.done():
                await asyncio.wait([group], timeout=0.1)
                if cancel.is_set():
                    group.cancel()
                    break
            await group
        except asyncio.CancelledError:
            group.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(group, return_exceptions=True)
