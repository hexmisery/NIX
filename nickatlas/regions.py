from urllib.parse import urlsplit

CIS_TLDS = {
    "ru",
    "su",
    "ua",
    "by",
    "kz",
    "uz",
    "kg",
    "tj",
    "tm",
    "am",
    "az",
    "md",
    "ge",
    "бел",
    "xn--90ais",
    "xn--p1ai",
    "рф",
    "укр",
    "xn--j1amh",
}
CIS_TAGS = {
    "ru",
    "ua",
    "by",
    "kz",
    "russia",
    "russian",
    "ukraine",
    "ukrainian",
    "belarus",
    "kazakhstan",
}
US_TAGS = {"us", "usa", "united states", "american"}
PRIORITIES = {
    "ru": "Россия",
    "all": "Все регионы",
    "cis": "СНГ и Украина",
    "world": "Международные",
    "by": "Беларусь",
    "europe": "Европа",
    "us": "США",
}

EUROPE_TLDS = set(
    "eu uk de fr pl nl be cz sk at ch it es pt fi se no dk is ie ee lv lt ro bg hu hr si rs ba me mk al gr mt cy lu li".split()
)
EUROPE_TAGS = {
    "europe",
    "european",
    "german",
    "germany",
    "french",
    "france",
    "polish",
    "poland",
    "uk",
    "british",
    "english uk",
    "dutch",
    "netherlands",
}


def in_priority(url, tags, priority):
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    tld = host.rsplit(".", 1)[-1]
    marks = {str(t).casefold() for t in tags}
    if priority == "by":
        return tld in {"by", "бел", "xn--90ais"} or bool(
            marks & {"by", "belarus", "belarusian"}
        )
    if priority == "europe":
        return tld in EUROPE_TLDS or bool(marks & EUROPE_TAGS)
    if priority == "us":
        return region_of(url, tags) == "us"
    return False


def region_of(url, tags=()):
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    tld = host.rsplit(".", 1)[-1]
    clean = {str(tag).casefold() for tag in tags}
    if tld in CIS_TLDS or clean & CIS_TAGS:
        return "cis"
    if tld == "us" or clean & US_TAGS:
        return "us"
    return "world"


def regional_order(urls, tags=None, priority="all", preserve_order=False):
    if priority not in PRIORITIES:
        raise ValueError("Неизвестный приоритет регионов")
    tags = tags or {}
    if priority in SCOPES and priority != "all":
        ordered = list(dict.fromkeys(urls)) if preserve_order else sorted(set(urls))
        return [
            url for url in ordered if matches_scope(url, tags.get(url, ()), priority)
        ]
    if priority in ("by", "europe", "us"):
        ordered = list(dict.fromkeys(urls)) if preserve_order else sorted(set(urls))
        return [u for u in ordered if in_priority(u, tags.get(u, ()), priority)] + [
            u for u in ordered if not in_priority(u, tags.get(u, ()), priority)
        ]
    groups = {"cis": [], "us": [], "world": []}
    for url in dict.fromkeys(urls) if preserve_order else sorted(set(urls)):
        groups[region_of(url, tags.get(url, ()))].append(url)
    countries = {"ru": [], "ua": [], "other": []}
    for url in groups["cis"]:
        tld = (urlsplit(url).hostname or "").rsplit(".", 1)[-1].lower()
        marks = {str(t).casefold() for t in tags.get(url, ())}
        country = (
            "ua"
            if tld in ("ua", "укр", "xn--j1amh")
            or marks & {"ua", "ukraine", "ukrainian"}
            else "ru"
            if tld in ("ru", "su", "рф", "xn--p1ai")
            or marks & {"ru", "russia", "russian"}
            else "other"
        )
        countries[country].append(url)
    groups["cis"] = []
    for i in range(max((len(g) for g in countries.values()), default=0)):
        for name in ("ru", "ua", "other"):
            if i < len(countries[name]):
                groups["cis"].append(countries[name][i])
    if priority == "ru":
        return (
            countries["ru"]
            + countries["ua"]
            + countries["other"]
            + groups["us"]
            + groups["world"]
        )
    if priority == "cis":
        return groups["cis"] + groups["us"] + groups["world"]
    if priority == "world":
        return groups["us"] + groups["world"] + groups["cis"]
    result = []
    for i in range(max((len(g) for g in groups.values()), default=0)):
        for name in ("cis", "us", "world"):
            if i < len(groups[name]):
                result.append(groups[name][i])
    return result


SCOPES = {
    "all": "Worldwide",
    "cis_scope": "CIS & Russian-speaking",
    "asia_scope": "Asia",
    "europe_scope": "Europe",
    "americas_scope": "Americas",
}
PRIORITIES.update(SCOPES)
CIS_TAGS.update(
    {
        "uz",
        "uzbek",
        "uzbekistan",
        "kazakh",
        "kk",
        "ky",
        "kyrgyz",
        "kyrgyzstan",
        "tg",
        "tajik",
        "tajikistan",
        "tk",
        "turkmen",
        "turkmenistan",
        "be",
        "belarusian",
        "ukrainian",
        "русский",
        "русскоязычный",
        "казахский",
        "узбекский",
        "qazaq",
        "oʻzbek",
    }
)
CIS_TLDS.update({"рус", "қаз", "укр"})
ASIA_TLDS = set(
    "cn jp kr kp tw hk mo mn in pk bd lk np bt mv af ir iq il jo lb sy sa ae qa bh kw om ye tr cy ps sg my id th vn ph la kh mm bn tl kz uz kg tj tm az am ge 中国 中國 香港 台湾 台灣 新加坡 한국 भारत asia".split()
)
ASIA_TAGS = set(
    "asia asian cn china chinese zh zh-cn zh-tw ja jp japan japanese ko kr korea korean kazakhstan kazakh kk uzbekistan uzbek uz kyrgyzstan kyrgyz ky tajikistan tajik tg turkmenistan turkmen tk india indian hindi hi indonesia indonesian id vietnam vietnamese vi thailand thai th persian fa arabic ar china japanese korean казахский узбекский".split()
)
AMERICAS_TLDS = set(
    "us ca mx br ar cl co pe uy py bo ec ve gy sr cr pa gt hn sv ni bz cu do ht jm tt bs bb pr".split()
)
AMERICAS_TAGS = {
    "us",
    "usa",
    "united states",
    "american",
    "canada",
    "canadian",
    "brazil",
    "brazilian",
    "mexico",
    "mexican",
    "argentina",
    "argentinian",
    "chile",
    "colombia",
    "peru",
    "pt-br",
    "en-us",
    "en-ca",
}


def marks_of(tags):
    if not isinstance(tags, (list, tuple, set)):
        return set()
    marks = {str(t).strip().casefold().replace("_", "-") for t in tags}
    return marks | {mark.split("-", 1)[0] for mark in marks}


def matches_scope(url, tags=(), scope="all"):
    if scope not in SCOPES or scope == "all":
        return True
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        tld = host.rsplit(".", 1)[-1]
        tld = tld.encode("ascii").decode("idna") if tld.startswith("xn--") else tld
    except (ValueError, UnicodeError):
        return False
    marks = marks_of(tags)
    if scope == "cis_scope":
        return tld in CIS_TLDS or bool(marks & CIS_TAGS)
    if scope == "asia_scope":
        return tld in ASIA_TLDS or bool(marks & ASIA_TAGS)
    if scope == "europe_scope":
        return tld in EUROPE_TLDS or bool(marks & EUROPE_TAGS)
    return tld in AMERICAS_TLDS or bool(marks & AMERICAS_TAGS)


def normalize_scope(value):
    return {
        "ru": "cis_scope",
        "by": "cis_scope",
        "cis": "cis_scope",
        "europe": "europe_scope",
        "us": "americas_scope",
        "world": "all",
    }.get(value, value if value in SCOPES else "all")
