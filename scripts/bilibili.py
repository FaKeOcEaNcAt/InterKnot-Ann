import http.client
import re
import ssl
import time
from calendar import monthrange
from datetime import datetime
from urllib.parse import urlencode, urlsplit

from scripts.model import BILI_ID, CST, UID, UNSAFE, Invalid, canonical, decode, digest, require, validate_record

HOST = "api.bilibili.com"
ENDPOINT = "/x/polymer/web-dynamic/v1/opus/feed/space"
DETAIL = "/x/polymer/web-dynamic/v1/detail"
MAX_RESPONSE = 2 * 1024 * 1024
TIMEOUT = 12
SUPPORTED = {"DYNAMIC_TYPE_ARTICLE", "DYNAMIC_TYPE_DRAW", "DYNAMIC_TYPE_WORD"}
SKIP = {"DYNAMIC_TYPE_FORWARD", "DYNAMIC_TYPE_AV", "DYNAMIC_TYPE_LIVE_RCMD",
        "DYNAMIC_TYPE_LIVE", "DYNAMIC_TYPE_MUSIC", "DYNAMIC_TYPE_PGC",
        "DYNAMIC_TYPE_NONE", "DYNAMIC_TYPE_COURSES", "DYNAMIC_TYPE_UGC_SEASON"}
MEDIA_HOST = re.compile(r"i[0-3]\.hdslb\.com")
MEDIA_PATH = re.compile(r"/bfs/[a-zA-Z0-9_/-]+\.(?:jpg|jpeg|png)")


class Retryable(Invalid):
    pass


def request_json(endpoint, params, host=HOST):
    path = endpoint + "?" + urlencode(params)
    connection = http.client.HTTPSConnection(host, timeout=TIMEOUT,
                                              context=ssl.create_default_context())
    try:
        connection.request("GET", path, headers={
            "Accept": "application/json",
            "User-Agent": "Inter-Knot-Announcements/1.0",
        })
        response = connection.getresponse()
        status = response.status
        if status in (408, 429) or 500 <= status <= 599:
            raise Retryable("{} HTTP {}".format(host, status))
        require(status == 200, "{} HTTP {} (redirects and access denials are terminal)".format(host, status))
        require(response.headers.get_content_type() == "application/json", "unexpected response MIME type")
        require(response.headers.get("Content-Encoding", "identity") == "identity", "unexpected encoding")
        deadline = time.monotonic() + TIMEOUT
        body = bytearray()
        while True:
            require(time.monotonic() < deadline, "response deadline exceeded")
            chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            require(len(body) <= MAX_RESPONSE, "response exceeds byte limit")
        return decode(body)
    finally:
        connection.close()


def get_json(endpoint, params, host=HOST):
    for attempt in range(3):
        try:
            return request_json(endpoint, params, host)
        except ssl.SSLCertVerificationError:
            raise Invalid(host + " TLS certificate verification failed") from None
        except (OSError, http.client.HTTPException, Retryable) as error:
            reason = str(error) if isinstance(error, Retryable) else type(error).__name__
            if attempt == 2:
                raise Invalid(host + " transport failed: " + reason) from None
            print("{} retry {}/2: {}".format(host, attempt + 1, reason), flush=True)
            time.sleep(3 * 2 ** attempt)


def parse_page(payload):
    require(isinstance(payload, dict) and type(payload.get("code")) is int, "invalid Bilibili envelope")
    require(payload["code"] == 0, "Bilibili API code {}".format(payload["code"]))
    data = payload.get("data")
    require(isinstance(data, dict) and isinstance(data.get("items"), list)
            and type(data.get("has_more")) is bool and len(data["items"]) <= 100,
            "unexpected Bilibili page schema")
    offset = data.get("offset")
    if data["has_more"]:
        require(isinstance(offset, str) and re.fullmatch(r"[A-Za-z0-9_=+/.-]{1,512}", offset),
                "invalid Bilibili pagination cursor")
    return data["items"], offset if data["has_more"] else None


def get_page(offset):
    return get_json(ENDPOINT, {"host_mid": UID, "offset": offset})


def get_detail(identifier):
    payload = get_json(DETAIL, {"id": identifier})
    require(isinstance(payload, dict) and type(payload.get("code")) is int, "invalid Bilibili detail envelope")
    require(payload["code"] == 0, "Bilibili detail API code {} (author and publication time unverified)".format(
        payload["code"]
    ))
    item = obj(obj(payload, "data"), "item")
    require(item.get("id_str") == identifier, "detail ID does not match the account feed")
    return item


def classify(title, text):
    text = re.split(r"——\s*欢迎来到|▼\s*《绝区零》", text, maxsplit=1)[0]
    heading = title + "\n" + text[:250]
    sections = text.splitlines()
    if re.search(r"\d+\.\d+\s*版本.*(?:更新公告|更新说明)", title) and (
        "更新开始时间" in text or "版本全新内容" in text or re.search(r"版本「[^」]+」更新公告$", title)
    ):
        return "version"
    if re.search(r"调频|频段|独家频道", title) and re.search(r"概率|限时|调频时间|频段时间", title + text):
        return "signal"
    if re.search(r"活动|限时开放", heading) and (
        any("活动时间" in line or "参与条件" in line for line in sections)
        or re.search(r"\d{1,2}[月/]\d{1,2}.*(?:开放|开启|结束)", text)
        or ("活动介绍" in title and "版本主题活动" in text)
    ):
        return "event"
    if re.search(r"维护|补偿", title) and re.search(r"维护时间|停服|补偿内容|游戏内邮件", text):
        return "maintenance"
    if re.search(r"修复|异常|系统|适配说明", title) and re.search(r"已修复|修复了|调整后|已知问题|系统优化|已支持", text):
        return "system"
    return "other"


def obj(parent, key):
    value = parent.get(key)
    require(isinstance(value, dict), "missing feed object: " + key)
    return value


def clean(value, limit):
    require(isinstance(value, str) and len(value) <= limit, "invalid feed text")
    return UNSAFE.sub("", value.replace("\r\n", "\n").replace("\r", "\n")).strip()


def lead(text):
    prefix = re.sub(r"^互动抽奖\s*", "", text)
    prefix = re.sub(r"^(?:\s*#[^#\n]{1,50}#[\s\u200b]*)+", "", prefix).strip()
    return re.split(r"〖|(?<=说明)\s+|(?<=介绍)\s+", prefix.split("\n", 1)[0], maxsplit=1)[0].strip()


def eligible(title, body):
    if not title or re.search(r"同人征集|角色PV|音乐平台|表情包|头像|月历壁纸|未归档影像|生日快乐", title):
        return False
    return classify(title, body) != "other" or not re.search(r"抽奖|转发.{0,12}抽|周边上新|线下快闪", body)


def discovery(entry, excluded):
    require(isinstance(entry, dict), "invalid opus discovery record")
    identifier = entry.get("opus_id")
    require(isinstance(identifier, str) and BILI_ID.fullmatch(identifier), "invalid opus discovery ID")
    require(entry.get("jump_url") in (canonical(identifier), "//www.bilibili.com/opus/" + identifier),
            "unexpected opus discovery URL")
    if identifier in excluded:
        return None
    body = clean(entry.get("content"), 100000)
    return identifier if eligible(lead(body), body) else None


def media_references(major, major_type):
    key = {"MAJOR_TYPE_OPUS": "opus", "MAJOR_TYPE_DRAW": "draw", "MAJOR_TYPE_ARTICLE": "article"}.get(major_type)
    if key is None:
        return []
    module = obj(major, key)
    values = module.get({"opus": "pics", "draw": "items", "article": "covers"}[key], [])
    require(isinstance(values, list) and len(values) <= 30, "invalid feed images")
    refs = []
    for entry in values:
        url = (entry.get("url") or entry.get("src")) if isinstance(entry, dict) else entry
        if not isinstance(url, str) or len(url) > 500 or re.search(r"[^\x21-\x7e]|\\", url):
            continue
        try:
            parts = urlsplit("https:" + url if url.startswith("//") else url)
        except ValueError:
            continue
        if (parts.scheme == "https" and MEDIA_HOST.fullmatch(parts.netloc)
                and MEDIA_PATH.fullmatch(parts.path) and not parts.query and not parts.fragment):
            refs.append("https://" + parts.netloc + parts.path)
    return refs


def normalize(item, excluded):
    require(isinstance(item, dict) and isinstance(item.get("type"), str), "invalid feed item")
    kind = item["type"]
    if kind in SKIP:
        return None
    require(kind in SUPPORTED, "unknown Bilibili item type")
    identifier = item.get("id_str")
    require(isinstance(identifier, str) and BILI_ID.fullmatch(identifier), "invalid feed ID")
    if identifier in excluded:
        return None
    modules = obj(item, "modules")
    author = obj(modules, "module_author")
    require(type(author.get("mid")) in (int, str) and str(author["mid"]) == UID, "unexpected feed author")
    stamp = author.get("pub_ts")
    require(type(stamp) is int and 1550000000 <= stamp <= 4102444800, "invalid source publication time")
    dynamic = obj(modules, "module_dynamic")
    major = dynamic.get("major") or {}
    require(isinstance(major, dict), "invalid major module")
    major_type = major.get("type")
    if kind == "DYNAMIC_TYPE_ARTICLE":
        require(major_type in ("MAJOR_TYPE_OPUS", "MAJOR_TYPE_ARTICLE"), "unknown article module")
    raw_title = ""
    if major_type == "MAJOR_TYPE_OPUS":
        opus = obj(major, "opus")
        raw_title = opus.get("title") or ""
        body = obj(opus, "summary").get("text")
    elif major_type == "MAJOR_TYPE_ARTICLE":
        article = obj(major, "article")
        raw_title = article.get("title")
        body = article.get("desc")
    else:
        body = obj(dynamic, "desc").get("text")

    original = clean(body, 100000)
    title = clean(raw_title, 1000)
    if not title:
        title = lead(original)
    if not eligible(title, original):
        return None
    if dynamic.get("additional") and isinstance(dynamic["additional"], dict):
        if dynamic["additional"].get("type") == "ADDITIONAL_TYPE_UPOWER_LOTTERY":
            return None
    category = classify(title, original)
    label = {
        "version": "涉及版本更新内容及安排",
        "event": "涉及游戏内活动及参与安排",
        "signal": "涉及代理人或音擎的限时调频",
        "maintenance": "涉及维护安排或补偿",
        "system": "涉及游戏系统调整或问题修复",
        "other": "内容归入其他官方资讯",
    }[category]
    summary = "绝区零官方在 Bilibili 发布了这条资讯，{}。请通过原文核对具体内容。".format(label)
    tag = modules.get("module_tag")
    require(tag is None or isinstance(tag, dict), "invalid pin module")
    # Fingerprint the fields returned by the feed. Some feed variants only expose excerpts.
    raw_hash = digest([title, original, media_references(major, major_type)])
    record = {
        "id": identifier, "source": "bilibili", "source_uid": UID,
        "title": " ".join(title.split())[:180], "category": category,
        "summary": summary, "content": [], "images": [],
        "published_at": datetime.fromtimestamp(stamp, CST).isoformat(timespec="seconds"),
        "updated_at": None, "source_url": canonical(identifier),
        "is_pinned": bool(tag and tag.get("text") == "置顶"),
        "content_hash": raw_hash, "ingest": "feed",
    }
    validate_record(record)
    return record


def three_months_ago(now):
    month_index = now.year * 12 + now.month - 4
    year, month = divmod(month_index, 12)
    month += 1
    return now.replace(year=year, month=month, day=min(now.day, monthrange(year, month)[1]))


def collect(page_limit, interval, excluded, cutoff):
    items = {}
    cursors = set()
    first_ids = set()
    checked = {}
    offset = ""
    for page in range(page_limit):
        raw, following = parse_page(get_page(offset))
        require(bool(raw), "empty feed page; archive preserved")
        dates = []
        for entry in raw:
            identifier = discovery(entry, excluded)
            if identifier is None:
                continue
            if identifier not in checked:
                time.sleep(interval)
                checked[identifier] = normalize(get_detail(identifier), excluded)
            item = checked[identifier]
            if item is None:
                continue
            published = datetime.fromisoformat(item["published_at"])
            dates.append(published)
            if published < cutoff:
                continue
            if page == 0:
                first_ids.add(identifier)
            items[identifier] = item
        if following is None or (page > 0 and dates and max(dates) < cutoff):
            break
        require(following not in cursors, "repeated Bilibili cursor")
        cursors.add(following)
        offset = following
        if page + 1 < page_limit:
            time.sleep(interval)
    else:
        print("Page budget reached; the three-month window may be incomplete")
    require(bool(items), "no eligible feed records; archive preserved")
    print("Fetched {} pages, {} eligible items".format(page + 1, len(items)))
    return items, first_ids
