import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "announcements.json"
UID = "1636034895"
ORIGIN = "https://www.bilibili.com"
OFFICIAL = "https://zenless.hoyoverse.com"
OFFICIAL_CHANNEL = "288"
CN_CHANNEL = "273"
CN = "https://zzz.mihoyo.com"
SOURCE_LABELS = {"bilibili": "BiliBili", "mihoyo": "miHoYo-CN", "hoyoverse": "HoYoVerse-Global"}
CST = timezone(timedelta(hours=8))
CATEGORIES = {
    "version": ("版本更新", "UPDATE"),
    "event": ("活动公告", "EVENT"),
    "maintenance": ("维护补偿", "SERVICE"),
    "signal": ("代理人调频", "SIGNAL"),
    "system": ("系统修复", "SYSTEM"),
    "other": ("其他官方资讯", "INTEL"),
}
BILI_ID = re.compile(r"[1-9][0-9]{14,21}")
OFFICIAL_ID = re.compile(r"(?:hoyo|mihoyo)-[1-9][0-9]{3,11}")
ID = re.compile(r"(?:[1-9][0-9]{14,21}|(?:hoyo|mihoyo)-[1-9][0-9]{3,11})")
REMOTE_IMAGE = re.compile(r"https://i[0-3]\.hdslb\.com/bfs/[A-Za-z0-9_/-]{1,400}\.(?:jpg|jpeg|png)(?:@[0-9]{2,4}w\.(?:jpg|png))?")
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-5][0-9]")
DIGEST = re.compile(r"[0-9a-f]{64}")
IMAGE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\.(?:jpg|png)")
UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\ud800-\udfff]")
MAX_STORE = 32 * 1024 * 1024


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=lambda _: require(False, "invalid JSON constant"))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def valid_text(value, limit):
    return (isinstance(value, str) and 0 < len(value) <= limit
            and bool(value.strip()) and not UNSAFE.search(value))


def date(value):
    require(isinstance(value, str) and STAMP.fullmatch(value), "invalid timestamp")
    return datetime.fromisoformat(value)


def canonical(identifier):
    if OFFICIAL_ID.fullmatch(identifier):
        prefix, number = identifier.split("-", 1)
        return (CN + "/news/" if prefix == "mihoyo" else OFFICIAL + "/zh-cn/news/") + number
    require(BILI_ID.fullmatch(identifier), "invalid Bilibili ID")
    return ORIGIN + "/opus/" + identifier


def reviewed_media():
    media = decode((ROOT / "config" / "remote-images.json").read_bytes())
    require(isinstance(media, dict) and len(media) <= 5000, "invalid remote image manifest")
    for identifier, item in media.items():
        require(BILI_ID.fullmatch(identifier) and isinstance(item, dict) and item.keys() == {
            "url", "thumbnail", "caption"
        }, "invalid remote image entry")
        require(all(isinstance(item[k], str) and REMOTE_IMAGE.fullmatch(item[k])
                    for k in ("url", "thumbnail")), "unsafe remote image URL")
        require(valid_text(item["caption"], 160), "invalid remote image caption")
    return media


def validate_record(item):
    fields = {
        "id", "source", "source_uid", "title", "category", "summary", "content",
        "images", "published_at", "updated_at", "source_url", "is_pinned",
        "content_hash", "ingest",
    }
    require(isinstance(item, dict) and item.keys() == fields, "invalid record fields")
    identifier = item["id"]
    require(isinstance(identifier, str) and ID.fullmatch(identifier), "invalid source ID")
    origin = (("mihoyo", CN_CHANNEL) if identifier.startswith("mihoyo-") else
              ("hoyoverse", OFFICIAL_CHANNEL) if identifier.startswith("hoyo-") else ("bilibili", UID))
    require((item["source"], item["source_uid"]) == origin, "invalid origin")
    require(item["source_url"] == canonical(identifier), "invalid source URL")
    require(valid_text(item["title"], 180) and valid_text(item["summary"], 240), "invalid title or summary")
    require(isinstance(item["category"], str) and item["category"] in CATEGORIES, "invalid category")
    require(type(item["is_pinned"]) is bool, "invalid pin")
    require(item["ingest"] in ("feed", "editorial"), "invalid provenance")
    require(isinstance(item["content_hash"], str) and DIGEST.fullmatch(item["content_hash"]), "invalid hash")
    published = date(item["published_at"])
    if item["updated_at"] is not None:
        require(date(item["updated_at"]) >= published, "update precedes publication")
    content = item["content"]
    require(isinstance(content, list) and len(content) <= 500, "invalid content blocks")
    for block in content:
        require(isinstance(block, dict) and block.keys() == {"type", "text"}
                and block["type"] in ("paragraph", "heading")
                and valid_text(block["text"], 2000), "invalid content block")
    images = item["images"]
    require(isinstance(images, list) and len(images) <= 6, "invalid image list")
    for image in images:
        require(isinstance(image, dict) and image.keys() == {
            "file", "size", "thumbnail", "thumbnail_size", "caption", "after_block"
        }, "invalid image fields")
        for name_key, size_key, limit in (("file", "size", 1600), ("thumbnail", "thumbnail_size", 520)):
            name, size = image[name_key], image[size_key]
            require(isinstance(name, str) and IMAGE_NAME.fullmatch(name), "unsafe image path")
            require(isinstance(size, list) and len(size) == 2
                    and all(type(n) is int and 1 <= n <= limit for n in size), "invalid image dimensions")
        require(valid_text(image["caption"], 160), "invalid image caption")
        require(type(image["after_block"]) is int and 0 <= image["after_block"] <= len(content),
                "invalid image position")


def validate_store(store):
    require(isinstance(store, dict) and store.keys() == {"schema", "last_changed_sync", "items"}
            and type(store["schema"]) is int and store["schema"] == 1, "invalid archive schema")
    if store["last_changed_sync"] is not None:
        date(store["last_changed_sync"])
    require(isinstance(store["items"], list), "invalid archive items")
    seen = set()
    for item in store["items"]:
        validate_record(item)
        require(item["id"] not in seen, "duplicate archive ID")
        seen.add(item["id"])
    return store


def load_store(path=DATA):
    with path.open("rb") as file:
        raw = file.read(MAX_STORE + 1)
    require(len(raw) <= MAX_STORE, "archive too large")
    return validate_store(decode(raw))
