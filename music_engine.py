import html
from difflib import SequenceMatcher
import http.cookiejar
import json
import re
import ssl
import time
import random
import threading
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
import database as db

_SSL_CTX = ssl.create_default_context()
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_COOKIE_JAR = http.cookiejar.CookieJar()

class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            newurl.encode("ascii")
        except UnicodeEncodeError:
            parsed = urllib.parse.urlsplit(newurl)
            safe_path = urllib.parse.quote(parsed.path, safe="/%:@+-_~.")
            safe_query = urllib.parse.quote(parsed.query, safe="=&?/%:@+-_~.")
            newurl = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, safe_path, safe_query, parsed.fragment))
        newurl = newurl.replace(" ", "%20")
        p = urllib.parse.urlsplit(newurl)
        new_headers = {
            "User-Agent": _UA,
            "Accept": "*/*",
            "Referer": f"{p.scheme}://{p.netloc}/"
        }
        if req.has_header("Range"):
            new_headers["Range"] = req.headers["Range"]
        return urllib.request.Request(newurl, headers=new_headers, method="GET")

_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_COOKIE_JAR),
    urllib.request.HTTPSHandler(context=_SSL_CTX),
    SafeRedirectHandler()
)

_api_executor = ThreadPoolExecutor(max_workers=12)
_wave_executor = ThreadPoolExecutor(max_workers=12)
_stream_executor = ThreadPoolExecutor(max_workers=2)
_playback_sources = ThreadPoolExecutor(max_workers=8)
_prefetch_sources = ThreadPoolExecutor(max_workers=4)
_pending_prefetch: set[str] = set()

_stream_candidates: dict[str, tuple[list[str], float]] = {}
_search_cache: dict[tuple[str, ...], tuple[dict, float]] = {}
_artist_cache: dict[str, tuple[dict, float]] = {}
_album_cache: dict[str, tuple[dict, float]] = {}
_provider_rows_cache: dict[str, tuple[list[dict], float]] = {}

_cache_lock = threading.Lock()

BANNED_WORDS = (
    "клип", "интервью", "вдудь", "подкаст", "реакция", "обзор",
    "караоке", "karaoke", "минус", "минусовка", "рингтон", "ringtone",
    "speed up", "slowed", "nightcore", "bass boosted", "отрывок", "snippet"
)

CLEAN_TITLE_RE = re.compile(
    r"\s*[\(\[]\s*(?:official\s+audio|audio|lyrics?|prod\.?.*?|feat\.?.*?|ft\.?.*?|официальное\s+аудио)\s*[\)\]]",
    re.IGNORECASE
)

# Словарь популярных русскоязычных запросов и псевдонимов -> официальное имя в каталогах
ARTIST_ALIASES = {
    "арни": "Aarne",
    "эминем": "Eminem",
    "aarne": "Aarne",
    "морген": "MORGENSHTERN",
    "моргенштерн": "MORGENSHTERN",
    "тейп": "Big Baby Tape",
    "биг бейби тейп": "Big Baby Tape",
    "буда": "OG Buda",
    "ог буда": "OG Buda",
    "кизару": "kizaru",
    "фараон": "PHARAOH",
    "мияги": "Miyagi & Эндшпиль",
    "макан": "MACAN",
    "токсис": "Toxi$",
    "обладает": "OBLADAET",
    "маркул": "Markul",
    "федук": "FEDUK",
    "салуки": "SALUKI",
    "платина": "Платина",
    "яникс": "Yanix",
    "слава марлоу": "SLAVA MARLOW",
    "егор крид": "Егор Крид",
    "крид": "Егор Крид",
    "тимати": "Тимати",
    "джиган": "Джиган",
    "баста": "Баста",
    "скриптонит": "Скриптонит",
    "земфира": "Земфира",
    "кино": "Кино",
    "король и шут": "Король и Шут",
    "киш": "Король и Шут",
    "три дня дождя": "Три дня дождя",
    "лсп": "ЛСП",
    "элджей": "Элджей",
    "бушидо жо": "BUSHIDO ZHO",
    "bushido zho": "BUSHIDO ZHO",
    "френдли таг": "FRIENDLY THUG 52 NGG",
    "friendly thug": "FRIENDLY THUG 52 NGG",
    "алблак": "ALBLAK 52",
    "alblak": "ALBLAK 52",
    "майот": "MAYOT",
    "сода лав": "SODA LUV",
    "lovv66": "LOVV66",
    "ловв66": "LOVV66",
    "викенд": "The Weeknd",
    "уикенд": "The Weeknd",
    "зэ викенд": "The Weeknd",
    "линкин парк": "Linkin Park",
    "линкен парк": "Linkin Park",
    "имэджин дрэгонс": "Imagine Dragons",
    "имеджин драгонс": "Imagine Dragons",
    "имэджин драгонс": "Imagine Dragons",
    "билли айлиш": "Billie Eilish",
    "билли эйлиш": "Billie Eilish",
    "тейлор свифт": "Taylor Swift",
    "эд ширан": "Ed Sheeran",
    "ариана гранде": "Ariana Grande",
    "доджа кэт": "Doja Cat",
    "бруно марс": "Bruno Mars",
    "пост малон": "Post Malone",
    "пост мелон": "Post Malone",
    "джастин бибер": "Justin Bieber",
    "мэрилин мэнсон": "Marilyn Manson",
    "арктик манкис": "Arctic Monkeys",
    "арктик манкиз": "Arctic Monkeys",
    "туенти ван пилотс": "Twenty One Pilots",
    "лан дел рей": "Lana Del Rey",
    "лана дель рей": "Lana Del Rey",
    "фрэнк оушен": "Frank Ocean",
    "фрэнк оушн": "Frank Ocean",
    "тупак": "2Pac",
    "пятьдесят сент": "50 Cent",
    "фифти сент": "50 Cent",
    "дафт панк": "Daft Punk",
    "битлз": "The Beatles",
    "бейонсе": "Beyoncé",
    "бейонс": "Beyoncé",
    "металлика": "Metallica",
    "сабрина карпентер": "Sabrina Carpenter",
    "ред хот чили пепперс": "Red Hot Chili Peppers",
    "кинг энд джестер": "Король и Шут",
}

SIMILAR_ARTISTS_GRAPH = {
    "aarne": ["Big Baby Tape", "BUSHIDO ZHO", "OG Buda", "Toxi$", "FRIENDLY THUG 52 NGG", "kizaru", "Платина", "FEDUK"],
    "земфира": ["Би-2", "Сплин", "Мумий Тролль", "Диана Арбенина", "Кино", "Ночные Снайперы", "Агата Кристи", "Три дня дождя"],
    "morgenshtern": ["SLAVA MARLOW", "Элджей", "Big Baby Tape", "kizaru", "OG Buda", "Тимати", "Скриптонит", "Платина"],
    "баста": ["Гуф", "Мот", "Скриптонит", "Miyagi & Эндшпиль", "Каста", "HammAli & Navai", "MACAN", "Ноггано"],
    "три дня дождя": ["Мукка", "Пошлая Молли", "ЛСП", "PHARAOH", "Нервы", "Земфира", "Кишлак", "XOLIDAYBOY"],
    "кино": ["Наутилус Помпилиус", "Агата Кристи", "ДДТ", "Сплин", "Би-2", "Король и Шут", "Ария", "Сектор Газа"],
    "король и шут": ["КняZz", "Кино", "Сектор Газа", "Ария", "Кукрыниксы", "Агата Кристи", "Би-2", "Сплин"],
    "скриптонит": ["Miyagi & Эндшпиль", "Баста", "ЛСП", "104", "T-Fest", "Markul", "Oxxxymiron", "SALUKI"],
    "miyagi & эндшпиль": ["Скриптонит", "Матранг", "Баста", "Каспийский Груз", "Santiz", "Мот", "MACAN"],
    "macan": ["Jakone", "A.V.G", "Xcho", "Баста", "Ramil'", "Мот", "Miyagi & Эндшпиль", "HammAli & Navai"],
    "лсп": ["Oxxxymiron", "PHARAOH", "Скриптонит", "Три дня дождя", "Markul", "Gone.Fludd", "SALUKI", "Пошлая Молли"],
    "big baby tape": ["Aarne", "kizaru", "OG Buda", "Платина", "FRIENDLY THUG 52 NGG", "ALBLAK 52", "OBLADAET", "MORGENSHTERN"],
    "og buda": ["MAYOT", "Платина", "Aarne", "Big Baby Tape", "SODA LUV", "LOVV66", "BUSHIDO ZHO", "163ONMYNECK"],
    "the weeknd": ["Post Malone", "Drake", "Travis Scott", "Lana Del Rey", "Bruno Mars", "Doja Cat", "Rihanna", "Daft Punk"],
}

_TO_LATIN = dict(zip("абвгдежзийклмнопрстуфхцчшщъыьэюяё", (
    "a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n",
    "o", "p", "r", "s", "t", "u", "f", "h", "ts", "ch", "sh", "shch",
    "", "y", "", "e", "yu", "ya", "yo",
)))
_CYRILLIC_SOUNDS = {"дж": "j", "кс": "x", "кв": "qu", "ай": "i", "эй": "ay"}
_TO_CYRILLIC = {value: key for key, value in _TO_LATIN.items() if value}
_TO_CYRILLIC.update({
    "e": "е", "y": "й", "j": "дж", "c": "к", "ck": "к", "w": "в",
    "x": "кс", "kh": "х", "ph": "ф", "sch": "щ", "ia": "ия", "ya": "я",
})


def _replace_sounds(text: str, mapping: dict[str, str]) -> str:
    pattern = "|".join(sorted(mapping, key=len, reverse=True))
    return re.sub(pattern, lambda match: mapping[match[0]], text)


def _latin(text: str, phonetic: bool = False) -> str:
    if phonetic:
        text = _replace_sounds(text, _CYRILLIC_SOUNDS)
    return "".join(_TO_LATIN.get(char, char) for char in text)


def _search_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def _resolve_alias(query: str) -> str:
    query = " ".join((query or "").split())
    words = query.split()
    max_words = min(len(words), 5)
    for size in range(max_words, 0, -1):
        key = _search_text(" ".join(words[:size]))
        if alias := ARTIST_ALIASES.get(key):
            return " ".join([alias, *words[size:]])
    return query


def _catalog_queries(query: str) -> list[str]:
    primary = _resolve_alias(query)
    queries = [primary]
    if _search_text(primary) != _search_text(query):
        queries.append(query)
    elif re.search(r"[а-яё]", query, re.I):
        queries.extend(_latin(query.casefold(), phonetic) for phonetic in (True, False))
    elif re.fullmatch(r"[a-z0-9& .'-]{3,}", query, re.I):
        queries.append(_replace_sounds(query.casefold(), _TO_CYRILLIC))
    unique = {}
    for variant in queries:
        if key := _search_text(variant):
            unique.setdefault(key, variant)
    return list(unique.values())


def _phonetic_key(text: str) -> str:
    text = "".join(char for char in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(char) or char == "̆")
    text = _latin(unicodedata.normalize("NFC", text).casefold(), True)
    text = re.sub(r"\bthe\b", "", text)
    text = re.sub(r"ph", "f", text)
    text = re.sub(r"ck|(?<![csz])c(?![eiyh])", "k", text)
    text = re.sub(r"c(?=[eiy])", "s", text)
    text = re.sub(r"w", "v", text)
    text = re.sub(r"[aeiouy\W_]", "", text)
    return re.sub(r"(.)\1+", r"\1", text)


def _artist_score(name: str, queries: list[str]) -> float:
    canonical = _search_text(name)
    if not canonical:
        return 0.0
    phonetic = _phonetic_key(name)
    score = 0.0
    for query in queries:
        normalized = _search_text(query)
        if canonical == normalized:
            return 3.0
        if normalized and set(normalized.split()) <= set(canonical.split()):
            score = max(score, 2.0)
        if len(canonical) >= 3 and (f" {canonical} " in f" {normalized} "):
            score = max(score, 2.0)
        key = _phonetic_key(query)
        if len(key) >= 3 and key == phonetic:
            score = max(score, 2.5)
        elif len(key) >= 5 and len(phonetic) >= 5:
            similarity = SequenceMatcher(None, key, phonetic, autojunk=False).ratio()
            if similarity >= 0.8 and key[0] == phonetic[0]:
                score = max(score, similarity + 1)
    return score


def open_url_stream(url: str, extra_headers: dict | None = None, timeout: int = 8):
    p = urllib.parse.urlsplit(url)
    hdrs = {
        "User-Agent": _UA,
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Referer": f"{p.scheme}://{p.netloc}/"
    }
    if extra_headers:
        hdrs.update(extra_headers)
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    return _OPENER.open(req, timeout=timeout)

def _http_get(url: str, timeout: int = 5) -> bytes:
    with open_url_stream(url, timeout=timeout) as resp:
        return resp.read()

def _clean_title(title: str) -> str:
    t = html.unescape(title or "").strip()
    cleaned = CLEAN_TITLE_RE.sub("", t).strip()
    return cleaned or t

def _clean_search_words(q: str) -> str:
    s = html.unescape(q or "")
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)
    s = re.sub(r"\b(?:feat|ft|prod)\b\.?", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"[-–—,&/\\|]+", " ", s)
    return " ".join(s.split())

def _fmt_sec(sec) -> str:
    if not sec:
        return ""
    try:
        s = int(float(sec))
        return f"{s // 60}:{s % 60:02d}"
    except Exception:
        return ""

def _parse_duration_sec(dur_str: str) -> int:
    if not dur_str:
        return 0
    parts = [p.strip() for p in str(dur_str).split(":") if p.strip().isdigit()]
    if not parts:
        return 0
    sec = 0
    for p in parts:
        sec = sec * 60 + int(p)
    return sec

def _extract_primary_artist(artist_str: str, title_str: str = "") -> str:
    a = html.unescape(artist_str or "").strip()
    if (not a or a == "Исполнитель") and " - " in (title_str or ""):
        a = title_str.split(" - ", 1)[0].strip()
    a = re.split(r"[,&/]|feat\.?|ft\.?", a, flags=re.IGNORECASE)[0].strip()
    return a

def _is_valid_full_track(title: str, artist: str, dur_sec: int, dis_filters: dict | None = None, strict_artist_ban: bool = False) -> bool:
    if not title or not artist:
        return False
    low_t = title.lower()
    low_a = artist.lower()
    for bw in BANNED_WORDS:
        if bw in low_t or bw == low_a:
            return False
    if dur_sec > 0 and (dur_sec < 60 or dur_sec > 540):
        return False
    if dis_filters:
        sig = db.normalize_sig(artist, _clean_title(title))
        if sig in dis_filters["sigs"]:
            return False
        if strict_artist_ban:
            art_norm = db.normalize_artist(artist)
            if art_norm and art_norm in dis_filters["artists"]:
                return False
    return True

def _add_candidate_url(vid_key: str, url: str):
    if not vid_key or not url:
        return
    if "apple.com" in url or "mzstatic.com" in url:
        return
    with _cache_lock:
        existing, exp = _stream_candidates.get(vid_key, ([], 0))
        if time.time() > exp:
            existing = []
        if url not in existing:
            existing.append(url)
        if len(_stream_candidates) >= 2048 and vid_key not in _stream_candidates:
            _stream_candidates.pop(next(iter(_stream_candidates)))
        _stream_candidates[vid_key] = (existing[:8], time.time() + 7200)

# --- ИСТОЧНИК 1: HITMOTOP ---
HITMO_DOMAINS = ["https://rus.hitmotop.com", "https://hitmos.me", "https://eu.hitmotop.com"]
HITMO_META_RE = re.compile(r"data-musmeta='(\{[^']+\})'", re.IGNORECASE)
HITMO_DUR_RE = re.compile(r'class=["\']track__fulltime["\'][^>]*>\s*([0-9:]+)\s*<', re.IGNORECASE)

def _hitmotop_search(query: str, liked_sigs: set, dis_filters: dict | None = None, strict_artist_ban: bool = False, limit: int = 24) -> list[dict]:
    tracks = []
    clean_q = _clean_search_words(query)
    if not clean_q:
        return tracks

    q_enc = urllib.parse.quote(clean_q)
    raw_html = ""
    active_dom = HITMO_DOMAINS[0]

    for dom in HITMO_DOMAINS:
        try:
            raw_html = _http_get(f"{dom}/search?q={q_enc}", timeout=4).decode("utf-8", errors="ignore")
            if "data-musmeta" in raw_html or "/get/music/" in raw_html:
                active_dom = dom
                break
        except Exception:
            continue

    if not raw_html:
        return tracks

    seen_sigs = set()
    for m in HITMO_META_RE.finditer(raw_html):
        if len(tracks) >= limit:
            break
        try:
            meta = json.loads(html.unescape(m.group(1)))
        except Exception:
            continue

        snippet = raw_html[m.end():m.end() + 1800]
        dur_m = HITMO_DUR_RE.search(snippet)
        dur_str = dur_m.group(1).strip() if dur_m else ""
        dur_sec = _parse_duration_sec(dur_str)

        artist = _clean_title(meta.get("artist") or "")
        title = _clean_title(meta.get("title") or "")
        mp3_url = (meta.get("url") or "").replace("\\/", "/").strip()
        img_url = (meta.get("img") or "").replace("\\/", "/").strip()

        if not mp3_url or not _is_valid_full_track(title, artist, dur_sec or 180, dis_filters, strict_artist_ban):
            continue

        if mp3_url.startswith("/"):
            mp3_url = active_dom + mp3_url
        if img_url.startswith("/"):
            img_url = active_dom + img_url

        sig = db.normalize_sig(artist, title)
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)

        vid_key = f"q:{artist} - {title}"
        if dis_filters and vid_key in dis_filters["ids"]:
            continue

        _add_candidate_url(vid_key, mp3_url)

        tracks.append({
            "video_id": vid_key,
            "title": title,
            "artist": artist,
            "artist_id": "",
            "thumbnail": img_url,
            "duration": dur_str,
            "liked": sig in liked_sigs
        })

    return tracks

# --- ИСТОЧНИК 2: MUZOFOND ---
MUZO_ITEM_RE = re.compile(
    r'data-url=["\'](?P<url>https?://[^"\']+\.mp3)["\'][\s\S]{0,1400}?<span[^>]*class=["\']artist["\'][^>]*>(?P<artist>[\s\S]*?)</span>[\s\S]{0,400}?<span[^>]*class=["\']track["\'][^>]*>(?P<title>[\s\S]*?)</span>',
    re.IGNORECASE
)

def _muzofond_search(query: str, liked_sigs: set, dis_filters: dict | None = None, strict_artist_ban: bool = False, limit: int = 20) -> list[dict]:
    tracks = []
    clean_q = _clean_search_words(query)
    if not clean_q:
        return tracks

    q_enc = urllib.parse.quote(clean_q)
    raw_html = ""
    for dom in ("https://muzofond.fm", "https://mufm.me"):
        try:
            raw_html = _http_get(f"{dom}/collections/songs/{q_enc}", timeout=4).decode("utf-8", errors="ignore")
            if "data-url=" in raw_html:
                break
        except Exception:
            continue

    if not raw_html:
        return tracks

    seen_sigs = set()
    for m in MUZO_ITEM_RE.finditer(raw_html):
        if len(tracks) >= limit:
            break
        mp3_url = m.group("url").strip()
        artist = _clean_title(re.sub(r"<[^>]+>", "", m.group("artist")))
        title = _clean_title(re.sub(r"<[^>]+>", "", m.group("title")))

        if not mp3_url or not _is_valid_full_track(title, artist, 180, dis_filters, strict_artist_ban):
            continue

        sig = db.normalize_sig(artist, title)
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)

        vid_key = f"q:{artist} - {title}"
        if dis_filters and vid_key in dis_filters["ids"]:
            continue

        _add_candidate_url(vid_key, mp3_url)

        tracks.append({
            "video_id": vid_key,
            "title": title,
            "artist": artist,
            "artist_id": "",
            "thumbnail": "",
            "duration": "",
            "liked": sig in liked_sigs
        })

    return tracks

def _audius_search_tracks(query: str, liked_sigs: set, dis_filters: dict | None = None, strict_artist_ban: bool = False, limit: int = 10) -> list[dict]:
    tracks = []
    clean_q = _clean_search_words(query)
    if not clean_q:
        return tracks
    try:
        q_enc = urllib.parse.quote(clean_q)
        raw = _http_get(f"https://discoveryprovider.audius.co/v1/tracks/search?query={q_enc}&app_name=melora", timeout=4)
        data = json.loads(raw.decode("utf-8", errors="ignore"))
        for item in (data.get("data") or [])[:limit]:
            tid = item.get("id")
            dur_sec = int(item.get("duration") or 0)
            title = _clean_title(item.get("title") or "")
            artist = _clean_title((item.get("user") or {}).get("name") or "")
            if not tid or not _is_valid_full_track(title, artist, dur_sec, dis_filters, strict_artist_ban):
                continue
            stream_url = f"https://discoveryprovider.audius.co/v1/tracks/{tid}/stream?app_name=melora"
            art_obj = item.get("artwork") or {}
            thumb = art_obj.get("480x480") or art_obj.get("150x150") or ""
            vid_key = f"q:{artist} - {title}"
            _add_candidate_url(vid_key, stream_url)
            sig = db.normalize_sig(artist, title)
            tracks.append({
                "video_id": vid_key,
                "title": title,
                "artist": artist,
                "artist_id": "",
                "thumbnail": thumb,
                "duration": _fmt_sec(dur_sec),
                "liked": sig in liked_sigs
            })
    except Exception:
        pass
    return tracks

# --- APPLE ITUNES RU API (ОФИЦИАЛЬНЫЙ РЕЙТИНГ ПОПУЛЯРНОСТИ, АРТИСТЫ, АЛЬБОМЫ, ОБЛОЖКИ) ---
def _itunes_get(url: str, timeout: int = 4) -> list[dict]:
    try:
        raw = _http_get(url, timeout=timeout)
        data = json.loads(raw.decode("utf-8", errors="ignore"))
        return data.get("results", [])
    except Exception:
        return []

def _format_itunes_catalog_item(row: dict, liked_sigs: set, dis_filters: dict | None = None, strict_artist_ban: bool = False) -> dict | None:
    if row.get("wrapperType") != "track":
        return None
    raw_title = (row.get("trackName") or "").strip()
    artist_name = (row.get("artistName") or "").strip()
    try:
        dur_sec = int(float(row.get("trackTimeMillis") or 0) / 1000)
    except (ValueError, OverflowError, TypeError):
        return None

    if not _is_valid_full_track(raw_title, artist_name, dur_sec, dis_filters, strict_artist_ban):
        return None

    clean_t = _clean_title(raw_title)
    vid_key = f"q:{artist_name} - {clean_t}"
    if dis_filters and vid_key in dis_filters["ids"]:
        return None

    thumb = (row.get("artworkUrl100") or "").replace("100x100bb", "400x400bb")
    sig = db.normalize_sig(artist_name, clean_t)
    artist_id = row.get("artistId")
    return {
        "video_id": vid_key,
        "title": clean_t,
        "artist": artist_name,
        "artist_id": f"it_art_{artist_id}" if artist_id else "",
        "genre": row.get("primaryGenreName") or "",
        "thumbnail": thumb,
        "duration": _fmt_sec(dur_sec),
        "liked": sig in liked_sigs
    }

def _merge_and_deduplicate(track_lists: list[list[dict]], itunes_rows: list[dict] | None = None, limit: int = 26) -> list[dict]:
    cover_map = {}
    if itunes_rows:
        for r in itunes_rows:
            if r.get("wrapperType") == "track":
                art = (r.get("artworkUrl100") or "").replace("100x100bb", "400x400bb")
                sig = db.normalize_sig(r.get("artistName") or "", _clean_title(r.get("trackName") or ""))
                if art and sig:
                    cover_map[sig] = art

    merged = []
    seen_sigs = set()
    seen_pairs = set()

    for lst in track_lists:
        for t in (lst or []):
            sig = db.normalize_sig(t["artist"], t["title"])
            title_only = re.sub(r"[^a-zа-яё0-9]+", "", t["title"].lower())
            art_norm = db.normalize_artist(t["artist"])
            pair_key = f"{art_norm}::{title_only}"

            if not title_only or sig in seen_sigs or pair_key in seen_pairs:
                continue

            if sig in cover_map and (not t.get("thumbnail") or "hitmo" in t.get("thumbnail", "")):
                t["thumbnail"] = cover_map[sig]

            seen_sigs.add(sig)
            seen_pairs.add(pair_key)
            merged.append(t)
            if len(merged) >= limit:
                return merged

    return merged

_RECORDING_VERSIONS = {
    "live": {"live", "лайв", "концерт", "концертная", "концертный"},
    "remix": {"remix", "remixes", "ремикс", "ремиксы", "mashup", "bootleg"},
    "acoustic": {"acoustic", "акустика", "акустическая", "unplugged"},
    "instrumental": {"instrumental", "инструментал", "минусовка"},
    "cover": {"cover", "кавер", "tribute", "трибьют"},
    "edit": {"edit", "sped", "slowed", "nightcore", "spedup"},
}


def _search_key(text):
    text = "".join(char for char in unicodedata.normalize("NFD", text.casefold())
                   if not unicodedata.combining(char) or char == "\u0306")
    return _search_text(unicodedata.normalize("NFC", text))


def _recording_versions(title, version=""):
    markers = re.findall(r"[\(\[]([^\)\]]+)", title)
    markers.extend(re.split(r"\s[-–—]\s", title)[1:])
    words = set(_search_key(" ".join([version, *markers])).split())
    return {kind for kind, forms in _RECORDING_VERSIONS.items() if words & forms}


def _provider_rows(url: str, data_key: str | None = None) -> list[dict]:
    now = time.monotonic()
    with _cache_lock:
        cached = _provider_rows_cache.get(url)
        if cached and now < cached[1]:
            return cached[0]
    try:
        data = json.loads(_http_get(url, timeout=3))
        rows = data.get(data_key, []) if data_key and isinstance(data, dict) else data
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    except (OSError, ValueError):
        rows = []
    with _cache_lock:
        if len(_provider_rows_cache) >= 512 and url not in _provider_rows_cache:
            _provider_rows_cache.pop(next(iter(_provider_rows_cache)))
        _provider_rows_cache[url] = (rows, now + (900 if rows else 20))
    return rows


def _deezer_rows(endpoint: str, **params) -> list[dict]:
    query = urllib.parse.urlencode(params)
    return _provider_rows(f"https://api.deezer.com/{endpoint}?{query}", "data")


def _format_deezer_track(row, liked_sigs, dis_filters):
    artist_row = row.get("artist") or {}
    album = row.get("album") or {}
    artist, title = _clean_title(artist_row.get("name") or ""), _clean_title(row.get("title") or "")
    duration = row.get("duration")
    if not isinstance(duration, int) or not _is_valid_full_track(title, artist, duration, dis_filters):
        return None
    key = db.normalize_sig(artist, title)
    video_id = f"q:{artist} - {title}"
    if video_id in dis_filters["ids"]:
        return None
    artist_id = artist_row.get("id")
    rank = row.get("rank")
    return {
        "video_id": video_id, "title": title, "artist": artist,
        "artist_id": f"dz_art_{artist_id}" if isinstance(artist_id, int) else "",
        "thumbnail": album.get("cover_big") or album.get("cover_medium") or "",
        "duration": _fmt_sec(duration), "liked": key in liked_sigs,
        "catalog_rank": rank if isinstance(rank, int) else 0,
        "catalog_version": row.get("title_version") or "",
    }


def _catalog_jobs(jobs, timeout):
    try:
        for future in as_completed(jobs, timeout=timeout):
            try:
                yield jobs[future], future.result()
            except (OSError, ValueError, TypeError):
                continue
    except FuturesTimeoutError:
        pass
    finally:
        for future in jobs:
            future.cancel()


def search_catalog(query: str, liked_ids: set, kind: str = "all") -> dict:
    query = query.strip()[:160]
    queries = _catalog_queries(query)
    if not queries:
        return {"tracks": [], "artists": []}
    cache_key = (kind, *(variant.casefold() for variant in queries))
    liked_sigs = db.get_liked_sigs()
    dis = db.get_dislike_filters()
    now = time.monotonic()
    with _cache_lock:
        cached = _search_cache.get(cache_key)
        if cached and now < cached[1]:
            return {
                "tracks": [
                    {**track, "liked": db.normalize_sig(track["artist"], track["title"]) in liked_sigs}
                    for track in cached[0]["tracks"]
                    if track["video_id"] not in dis["ids"]
                    and db.normalize_sig(track["artist"], track["title"]) not in dis["sigs"]
                ],
                "artists": cached[0]["artists"],
            }

    jobs = {}
    for variant in queries:
        entities = (["song"] if kind != "artists" else []) + (["musicArtist"] if kind != "tracks" else [])
        for entity in entities:
            params = urllib.parse.urlencode({
                "term": variant, "media": "music", "entity": entity, "country": "RU", "limit": 35,
            })
            jobs[_api_executor.submit(_itunes_get, f"https://itunes.apple.com/search?{params}", 3)] = ("apple", entity)
            endpoint = "search" if entity == "song" else "search/artist"
            jobs[_api_executor.submit(_deezer_rows, endpoint, q=variant, limit=35)] = ("deezer", entity)

    search_keys = list(dict.fromkeys(_search_key(term) for term in (query, *queries)))
    words_by_query = [set(key.split()) for key in search_keys if key]
    requested_versions = {
        version for version, forms in _RECORDING_VERSIONS.items()
        if any(words & forms for words in words_by_query)
    }
    tracks = []
    artist_cards = {}

    def artist_quality(name):
        return 3 if _search_key(name) in search_keys else _artist_score(name, queries)

    for (provider, entity), rows in _catalog_jobs(jobs, 4.2):
        for row in rows:
            if entity == "musicArtist":
                name = (row.get("name") if provider == "deezer" else row.get("artistName")) or ""
                if not name or artist_quality(name) < 2:
                    continue
                artist_id = row.get("id") if provider == "deezer" else row.get("artistId")
                prefix = "dz_art_" if provider == "deezer" else "it_art_"
                card = {"name": name, "browse_id": f"{prefix}{artist_id}" if artist_id else "",
                        "thumbnail": row.get("picture_medium") or ""}
                key = _search_key(name)
                fans = row.get("nb_fan", 0)
                score = (artist_quality(name), provider == "deezer", fans if isinstance(fans, int) else 0)
                if key not in artist_cards or score > artist_cards[key][0]:
                    artist_cards[key] = (score, card)
                continue

            formatter = _format_deezer_track if provider == "deezer" else _format_itunes_catalog_item
            track = formatter(row, liked_sigs, dis)
            if not track:
                continue
            title, artist = _search_key(track["title"]), _search_key(track["artist"])
            if re.search(r"\b(tribute|karaoke|трибьют|караоке)\b", artist):
                continue
            versions = _recording_versions(track["title"], track.get("catalog_version", ""))
            if versions - requested_versions:
                continue
            title_words, artist_words = set(title.split()), set(artist.split())
            relevance = 0
            for words in words_by_query:
                if artist_words and artist_words < words and words - artist_words == title_words:
                    relevance = max(relevance, 5)
                elif title in search_keys:
                    relevance = max(relevance, 4)
                elif words <= title_words:
                    relevance = max(relevance, 3)
                elif words <= title_words | artist_words and words & title_words:
                    relevance = max(relevance, 2)
            if relevance == 0 and artist_quality(track["artist"]) >= 2.5:
                relevance = 1
            if relevance:
                popularity = track.pop("catalog_rank", 0)
                track.pop("catalog_version", None)
                tracks.append(((relevance, len(versions & requested_versions), provider == "deezer", popularity), track))

    tracks.sort(key=lambda item: item[0], reverse=True)
    best = tracks[0][0][0] if tracks else 0
    matching = [track for score, track in tracks if score[0] >= (best if best >= 4 else max(1, best - 1))]
    ranked_artists = sorted(artist_cards.values(), key=lambda item: item[0], reverse=True)
    if ranked_artists and ranked_artists[0][0][0] == 3:
        ranked_artists = [item for item in ranked_artists if item[0][0] == 3]
    result = {
        "tracks": _merge_and_deduplicate([matching], limit=12 if best >= 4 else 20),
        "artists": [card for _, card in ranked_artists[:8]],
    }
    if result["tracks"] or result["artists"]:
        with _cache_lock:
            if len(_search_cache) >= 256 and cache_key not in _search_cache:
                _search_cache.pop(next(iter(_search_cache)))
            _search_cache[cache_key] = (result, now + 600)
    return result


# --- ПРОФИЛЬ АРТИСТА ---
def get_artist_profile(browse_id: str, name: str, liked_ids: set) -> dict:
    clean_name = name.strip() if browse_id and name.strip() else _resolve_alias(_extract_primary_artist(name))
    cache_key = f"{browse_id}|{clean_name}".lower()
    liked_sigs = db.get_liked_sigs()
    dis_filters = db.get_dislike_filters()
    now = time.time()

    with _cache_lock:
        cached = _artist_cache.get(cache_key)
        if cached and now < cached[1]:
            prof = cached[0]
            songs_copy = [
                {**t, "liked": db.normalize_sig(t["artist"], t["title"]) in liked_sigs}
                for t in prof["top_songs"]
                if db.normalize_sig(t["artist"], t["title"]) not in dis_filters["sigs"]
            ]
            return {**prof, "top_songs": songs_copy}

    selected_id = re.fullmatch(r"dz_art_([0-9]+)", browse_id)
    artist_id = int(selected_id[1]) if selected_id else _deezer_artist_id(clean_name)
    params = urllib.parse.urlencode({
        "term": clean_name, "media": "music", "entity": "album", "country": "RU", "limit": 22,
    })
    jobs = {
        _api_executor.submit(_itunes_get, f"https://itunes.apple.com/search?{params}", 3): "albums",
        _api_executor.submit(_apple_songs, clean_name): "apple",
    }
    if artist_id:
        for source, limit in (("top", 26), ("related", 12)):
            jobs[_api_executor.submit(_deezer_rows, f"artist/{artist_id}/{source}", limit=limit)] = source
    rows = dict(_catalog_jobs(jobs, 4))
    apple_songs = [
        track for row in rows.get("apple", [])
        if (track := _format_itunes_catalog_item(row, liked_sigs, dis_filters))
        and _artist_key(track["artist"]) == _artist_key(clean_name)
        and not _recording_versions(track["title"])
    ]
    deezer_songs = [
        track for row in rows.get("top", [])
        if (track := _format_deezer_track(row, liked_sigs, dis_filters))
        and track["artist_id"] == f"dz_art_{artist_id}"
        and not _recording_versions(track["title"], track.get("catalog_version", ""))
    ]
    for track in deezer_songs:
        track.pop("catalog_rank", None)
        track.pop("catalog_version", None)
    top_songs = _merge_and_deduplicate([deezer_songs, apple_songs], limit=18)
    main_genre = next((track["genre"] for track in apple_songs if track.get("genre")), "")
    albums_by_title = {}
    for row in rows.get("albums", []):
        title = row.get("collectionName") or ""
        collection_id = row.get("collectionId")
        if not collection_id or not title or _artist_key(row.get("artistName") or "") != _artist_key(clean_name):
            continue
        albums_by_title.setdefault(_search_key(title), {
            "browse_id": f"it_alb_{collection_id}", "title": title, "artist": clean_name,
            "year": str(row.get("releaseDate") or "")[:4], "type": "Альбом",
            "thumbnail": (row.get("artworkUrl100") or "").replace("100x100bb", "400x400bb"),
        })
    albums = list(albums_by_title.values())
    photo = (albums[0]["thumbnail"] if albums else "") or (top_songs[0]["thumbnail"] if top_songs else "")

    similar_artists = [
        {"browse_id": f"dz_art_{row['id']}", "name": row["name"], "thumbnail": row.get("picture_medium") or ""}
        for row in rows.get("related", [])
        if isinstance(row.get("id"), int) and row.get("name")
        and _artist_key(row["name"]) != _artist_key(clean_name)
        and db.normalize_artist(row["name"]) not in dis_filters["artists"]
    ][:6]
    if not similar_artists:
        similar_artists = [
            {"browse_id": "", "name": name, "thumbnail": ""}
            for name in SIMILAR_ARTISTS_GRAPH.get(clean_name.lower(), [])[:6]
            if db.normalize_artist(name) not in dis_filters["artists"]
        ]

    profile = {
        "browse_id": browse_id,
        "name": clean_name or "Исполнитель",
        "photo": photo,
        "subscribers": main_genre or "Официальный каталог",
        "top_songs": top_songs,
        "albums": albums[:12],
        "similar_artists": similar_artists
    }

    if top_songs or albums:
        with _cache_lock:
            _artist_cache[cache_key] = (profile, time.time() + 900)
    return profile

# --- ТРЕКИ АЛЬБОМА ---
def get_album_tracks(browse_id: str, liked_ids: set, fallback_title: str = "", fallback_artist: str = "") -> dict:
    cache_key = f"{browse_id}|{fallback_artist}|{fallback_title}".lower()
    liked_sigs = db.get_liked_sigs()
    now = time.time()

    with _cache_lock:
        cached = _album_cache.get(cache_key)
        if cached and now < cached[1]:
            alb = cached[0]
            tracks_copy = [{**t, "liked": db.normalize_sig(t["artist"], t["title"]) in liked_sigs} for t in alb["tracks"]]
            return {**alb, "tracks": tracks_copy}

    if browse_id.startswith("it_alb_") or browse_id.startswith("itunes_alb_"):
        col_id = browse_id.replace("it_alb_", "").replace("itunes_alb_", "")
        rows = _itunes_get(f"https://itunes.apple.com/lookup?id={urllib.parse.quote(col_id)}&entity=song&country=RU", 5)
        alb_title = fallback_title or "Альбом"
        alb_artist = fallback_artist or "Исполнитель"
        alb_thumb = ""
        alb_year = ""
        tracks = []

        for r in rows:
            if r.get("wrapperType") == "collection":
                alb_title = r.get("collectionName") or alb_title
                alb_artist = r.get("artistName") or alb_artist
                alb_thumb = (r.get("artworkUrl100") or "").replace("100x100bb", "400x400bb")
                alb_year = str(r.get("releaseDate") or "")[:4]
            elif r.get("wrapperType") == "track":
                t_name = _clean_title(r.get("trackName") or "Трек")
                t_art = _extract_primary_artist(r.get("artistName") or alb_artist)
                dur_sec = int(float(r.get("trackTimeMillis") or 0) / 1000)
                if dur_sec < 60:
                    continue
                sig = db.normalize_sig(t_art, t_name)
                vid_key = f"q:{t_art} - {t_name}"
                tracks.append({
                    "video_id": vid_key,
                    "title": t_name,
                    "artist": t_art,
                    "thumbnail": alb_thumb or (r.get("artworkUrl100") or "").replace("100x100bb", "400x400bb"),
                    "duration": _fmt_sec(dur_sec),
                    "liked": sig in liked_sigs
                })

        if tracks:
            result = {
                "browse_id": browse_id,
                "title": alb_title,
                "artist": alb_artist,
                "year": alb_year,
                "thumbnail": alb_thumb,
                "tracks": tracks
            }
            with _cache_lock:
                _album_cache[cache_key] = (result, time.time() + 900)
            return result

    res = search_catalog(f"{fallback_artist} {fallback_title}", liked_ids, "tracks")
    return {
        "browse_id": browse_id,
        "title": fallback_title or "Альбом",
        "artist": fallback_artist or "Исполнитель",
        "year": "",
        "thumbnail": res["tracks"][0]["thumbnail"] if res["tracks"] else "",
        "tracks": res["tracks"]
    }

def wave_track_key(track: dict) -> str:
    artist = _resolve_alias(_extract_primary_artist(track["artist"], track["title"]))
    return db.normalize_sig(artist, _clean_title(track["title"]))


def _primary_credit(name):
    return re.split(r"\s*,\s*|\s+(?:feat\.?|ft\.?)\s+", name, maxsplit=1, flags=re.I)[0].strip()


def _artist_key(name):
    name = _primary_credit(name)
    exact = _search_text(name)
    return _search_key(ARTIST_ALIASES.get(exact, name)).replace(" ", "")


def _deezer_artist_id(name):
    expected = _artist_key(name)
    rows = _deezer_rows("search/artist", q=name, limit=12)
    matches = [row for row in rows if _artist_key(row.get("name") or "") == expected
               and isinstance(row.get("id"), int)]
    if matches:
        return max(matches, key=lambda row: row.get("nb_fan") or 0)["id"]
    return None


def _apple_songs(term):
    params = urllib.parse.urlencode({
        "term": term, "media": "music", "entity": "song", "country": "RU", "limit": 45,
    })
    return _itunes_get(f"https://itunes.apple.com/search?{params}", 2.5)


def _similar_recordings(artist, title):
    base = "https://labs.api.listenbrainz.org"
    query = urllib.parse.urlencode({"artist_credit_name": artist, "recording_name": title})
    matches = _provider_rows(f"{base}/acr-lookup/json?{query}")
    if not matches:
        return []
    mbid = matches[0].get("recording_mbid")
    if not isinstance(mbid, str) or not re.fullmatch(r"[a-f0-9-]{36}", mbid):
        return []
    query = urllib.parse.urlencode({
        "recording_mbids": mbid,
        "algorithm": "session_based_days_7500_session_300_contribution_5_threshold_15_limit_50_skip_30",
    })
    return _provider_rows(f"{base}/similar-recordings/json?{query}")


def _catalog_recording(artist, title, liked_sigs, dis):
    artist_key, title_key = _artist_key(artist), _search_key(title)
    for row in _deezer_rows("search", q=f"{artist} {title}", limit=12):
        track = _format_deezer_track(row, liked_sigs, dis)
        if track and _artist_key(track["artist"]) == artist_key and _search_key(track["title"]) == title_key:
            return track
    return None


def get_personalized_recommendations(
    seed_tracks: list[dict], liked_ids: set, *, page: int = 0, exclude: set[str] | None = None,
) -> dict:
    liked_sigs = db.get_liked_sigs()
    dis = db.get_dislike_filters()
    seen = set(exclude or ())
    names = {}
    favorites, history, favorite_tracks = {}, {}, {}
    for track in seed_tracks:
        name = _primary_credit(track["artist"])
        name = ARTIST_ALIASES.get(_search_text(name), name)
        key = _artist_key(name)
        if not key or name == "Исполнитель" or db.normalize_artist(name) in dis["artists"]:
            continue
        names.setdefault(key, name)
        if track.get("liked") or track["video_id"] in liked_ids:
            favorites[key] = favorites.get(key, 0) + 1
            favorite_tracks.setdefault(key, []).append(track)
            seen.add(wave_track_key(track))
        else:
            history[key] = min(4, history.get(key, 0) + min(track.get("play_count") or 1, 2))

    weights = favorites or history
    ranked = sorted(weights, key=weights.get, reverse=True)
    basis = ", ".join(names[key] for key in ranked[:3])
    known = set(favorites or history)
    if not ranked:
        for name in ("Земфира", "Баста", "Кино", "Три дня дождя", "Скриптонит", "Linkin Park"):
            if db.normalize_artist(name) not in dis["artists"]:
                key = _artist_key(name)
                names[key] = name
                ranked.append(key)

    if not ranked:
        return {"tracks": [], "basis": basis}
    primary = [ranked[(page * 2 + i) % len(ranked)] for i in range(min(4, len(ranked)))]
    if ranked[0] not in primary:
        primary[-1] = ranked[0]
    similarity_jobs = {}
    for key in [key for key in primary if key in favorite_tracks][:2]:
        tracks = favorite_tracks[key]
        seed = tracks[page % len(tracks)]
        future = _wave_executor.submit(_similar_recordings, seed["artist"], seed["title"])
        similarity_jobs[future] = (key, "similar")
    artist_ids = {}
    for key, artist_id in _catalog_jobs(
        {_wave_executor.submit(_deezer_artist_id, names[key]): key for key in primary}, 3.2
    ):
        if artist_id:
            artist_ids[key] = artist_id

    jobs = similarity_jobs
    for key in primary:
        if key in artist_ids:
            artist_id = artist_ids[key]
            for endpoint, limit in (("radio", 70), ("related", 24), ("top", 36)):
                jobs[_wave_executor.submit(_deezer_rows, f"artist/{artist_id}/{endpoint}", limit=limit)] = (key, endpoint)
        else:
            jobs[_wave_executor.submit(_apple_songs, names[key])] = (key, "apple")
    pools = {}
    related = {}
    genres = {}
    similar_titles = {}
    familiar_ids = {f"dz_art_{artist_ids[key]}" for key in known if key in artist_ids}

    def collect(track, score):
        if not track:
            return
        artist = track["artist"]
        key = wave_track_key(track)
        signature = db.normalize_sig(artist, track["title"])
        if (key in seen or signature in dis["sigs"] or track["video_id"] in dis["ids"]
                or db.normalize_artist(artist) in dis["artists"]
                or _recording_versions(track["title"], track.get("catalog_version", ""))
                or re.search(r"\b(tribute|karaoke|трибьют|караоке)\b", _search_key(artist))):
            return
        artist_key = _artist_key(artist)
        is_familiar = artist_key in known or track.get("artist_id") in familiar_ids
        pool = pools.setdefault((is_familiar, artist_key), {})
        score = (score, track.get("catalog_rank", 0))
        if key not in pool or score > pool[key][0]:
            pool[key] = (score, {**track, "wave_key": key})

    for (key, source), rows in _catalog_jobs(jobs, 3.6):
        strength = weights.get(key, 1)
        if source == "similar":
            for index, row in enumerate(rows[:30]):
                artist = row.get("artist_credit_name")
                title = row.get("recording_name")
                if not artist or not title or _artist_key(artist) in known:
                    continue
                track_key = wave_track_key({"artist": artist, "title": title})
                if track_key in seen:
                    continue
                score = 200 + 30 - index + strength
                if track_key not in similar_titles or score > similar_titles[track_key][0]:
                    similar_titles[track_key] = (score, artist, title)
            continue
        if source == "related":
            for index, row in enumerate(rows):
                artist = row.get("name") or ""
                artist_id = row.get("id")
                if artist and isinstance(artist_id, int) and _artist_key(artist) not in known:
                    score = strength * (len(rows) - index)
                    related[artist_id] = related.get(artist_id, 0) + score
            continue
        for row in rows:
            if source == "apple":
                track = _format_itunes_catalog_item(row, liked_sigs, dis, True)
                if not track or _artist_key(track["artist"]) != key:
                    continue
                if track["genre"]:
                    genres[track["genre"]] = max(genres.get(track["genre"], 0), strength)
            else:
                track = _format_deezer_track(row, liked_sigs, dis)
            collect(track, (120 if source == "radio" else 65) + strength)

    ranked_similar = sorted(similar_titles.items(), key=lambda item: item[1][0], reverse=True)
    if ranked_similar:
        existing = {key: track for pool in pools.values() for key, (_, track) in pool.items()}
        similar_jobs = {}
        for key, (score, artist, title) in ranked_similar[:12]:
            if key in existing:
                collect(existing[key], score)
            elif len(similar_jobs) < 5:
                job = _wave_executor.submit(_catalog_recording, artist, title, liked_sigs, dis)
                similar_jobs[job] = score
        for score, track in _catalog_jobs(similar_jobs, 2.4):
            collect(track, score)

    discovery_count = sum(len(pool) for (familiar, _), pool in pools.items() if not familiar)
    if discovery_count < 24:
        related_ids = sorted(related, key=related.get, reverse=True)
        offset = (page * 4) % max(1, len(related_ids))
        choices = (related_ids[offset:] + related_ids[:offset])[:5]
        more = {_wave_executor.submit(_deezer_rows, f"artist/{artist_id}/top", limit=24): related[artist_id]
                for artist_id in choices}
        for key in primary:
            for artist in SIMILAR_ARTISTS_GRAPH.get(names[key].casefold(), [])[:4]:
                if _artist_key(artist) not in known and len(more) < 8:
                    more[_wave_executor.submit(_apple_songs, artist)] = artist
        for relation, rows in _catalog_jobs(more, 2.8):
            for row in rows:
                if isinstance(relation, str):
                    track = _format_itunes_catalog_item(row, liked_sigs, dis, True)
                    if not track or _artist_key(track["artist"]) != _artist_key(relation):
                        continue
                else:
                    track = _format_deezer_track(row, liked_sigs, dis)
                collect(track, 95)

    if not any(pool for (familiar, _), pool in pools.items() if not familiar) and genres:
        genre = max(genres, key=genres.get)
        for _, rows in _catalog_jobs({_wave_executor.submit(_apple_songs, genre): genre}, 2):
            for row in rows:
                if row.get("primaryGenreName") == genre:
                    collect(_format_itunes_catalog_item(row, liked_sigs, dis, True), 30)

    def round_robin(familiar):
        choices = [sorted(pool.values(), key=lambda item: item[0])[-3:]
                   for (is_familiar, _), pool in pools.items() if is_familiar == familiar]
        while choices:
            choices.sort(key=lambda pool: pool[-1][0], reverse=True)
            for pool in choices:
                yield pool.pop()[1]
            choices = [pool for pool in choices if pool]

    discoveries, familiar = round_robin(False), round_robin(True)
    tracks = []
    from_library = 0
    for position in range(20):
        track = None
        if position % 4 == 3 and from_library < 5:
            track = next(familiar, None)
            from_library += track is not None
        if track is None:
            track = next(discoveries, None)
        if track is None and from_library < 5:
            track = next(familiar, None)
            from_library += track is not None
        if track is None:
            break
        if track["wave_key"] in seen:
            continue
        seen.add(track["wave_key"])
        track.pop("catalog_rank", None)
        track.pop("catalog_version", None)
        tracks.append(track)
    return {"tracks": tracks, "basis": basis}


def get_candidate_stream_urls(
    video_id: str, artist_hint: str = "", title_hint: str = "", *,
    exclude: list[str] | None = None, prefetch: bool = False,
) -> list[str]:
    ignored = set(exclude or [])
    with _cache_lock:
        cached, expires = _stream_candidates.get(video_id, ([], 0))
        urls = [url for url in cached if url not in ignored] if expires > time.time() else []
    if urls:
        return urls
    saved = db.get_cached_stream_url(video_id)
    if saved and saved not in ignored:
        return [saved]

    raw_query = f"{artist_hint} - {title_hint}" if artist_hint and title_hint else db.lookup_track_query_by_id(video_id)
    if " - " not in raw_query:
        return []
    artist, title = raw_query.split(" - ", 1)
    signature = db.normalize_sig(artist, title)
    short_query = _clean_search_words(f"{_extract_primary_artist(artist)} {_clean_title(title)}")
    if not short_query or signature in {"::", f"{db.normalize_artist(artist)}::"}:
        return []

    executor = _prefetch_sources if prefetch else _playback_sources
    providers = (_hitmotop_search, _muzofond_search, _audius_search_tracks)
    futures = [executor.submit(provider, short_query, set(), None, False, 12) for provider in providers]
    try:
        for future in as_completed(futures, timeout=4.5):
            for track in future.result():
                if db.normalize_sig(track["artist"], track["title"]) != signature:
                    continue
                with _cache_lock:
                    matches, expires = _stream_candidates.get(track["video_id"], ([], 0))
                    if expires > time.time():
                        urls.extend(url for url in matches if url not in ignored and url not in urls)
            if urls:
                for url in urls:
                    _add_candidate_url(video_id, url)
                return urls
    except FuturesTimeoutError:
        pass
    finally:
        for future in futures:
            future.cancel()
    return []


def remember_stream(video_id: str, url: str):
    with _cache_lock:
        if video_id in _stream_candidates:
            candidates, expires = _stream_candidates[video_id]
            _stream_candidates[video_id] = ([url, *(candidate for candidate in candidates if candidate != url)], expires)
    db.save_cached_stream_url(video_id, url)


def prefetch_streams(video_ids: list[str]):
    with _cache_lock:
        for video_id in dict.fromkeys(video_ids[:3]):
            if not video_id or len(video_id) > 500 or video_id in _pending_prefetch:
                continue
            if len(_pending_prefetch) >= 4:
                break
            _pending_prefetch.add(video_id)
            _stream_executor.submit(_safe_prefetch, video_id)


def _safe_prefetch(video_id: str):
    try:
        get_candidate_stream_urls(video_id, prefetch=True)
    finally:
        with _cache_lock:
            _pending_prefetch.discard(video_id)
