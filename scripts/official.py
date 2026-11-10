import re
import time
from datetime import datetime
from html.parser import HTMLParser

from scripts.bilibili import classify, clean, eligible, get_json
from scripts.model import CN_CHANNEL, CST, OFFICIAL_CHANNEL, OFFICIAL_ID, canonical, digest, require, validate_record

HOST = "sg-public-api-static.hoyoverse.com"
ENDPOINT = "/content_v2_user/app/3e9196a4b9274bd7/getContentList"
SITES = {
    "hoyoverse": (HOST, ENDPOINT, OFFICIAL_CHANNEL, "hoyo", "295", "296", "297"),
    "mihoyo": ("api-takumi-static.mihoyo.com", "/content_v2_user/app/706fd13a87294881/getContentList",
               CN_CHANNEL, "mihoyo", "278", "279", "280"),
}
PAGE_SIZE = 20
PUBLISH_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}")
EVENT_STAMP = r"[0-9]{4}/[0-9]{1,2}/[0-9]{1,2} [0-9]{2}:[0-9]{2}"
ACTIVITY_TIME = re.compile(
    r"活动时间(?:为)?[】〗：:\s]*(" + EVENT_STAMP + r"|[0-9]+\.[0-9]+版本更新后)"
    r"(?:（服务器时间）)?\s*[~～至]\s*(" + EVENT_STAMP + r")"
)
SUMMARIES = {
    "version": "官网发布了版本内容、更新安排及相关说明。具体变动请查看官方原文。",
    "event": "官网发布了活动及参与安排。具体时间、条件和奖励请查看官方原文。",
    "maintenance": "官网发布了维护或补偿安排。详细时间和领取条件请查看官方原文。",
    "signal": "官网发布了限时调频安排。频段、适用角色和开放时间请查看官方原文。",
    "system": "官网发布了系统调整、适配或问题修复说明。具体内容请查看官方原文。",
    "other": "这条资讯来自《绝区零》官网。完整内容请查看官方原文。",
}


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style") and not self.ignored:
            self.ignored = tag
        if tag in ("p", "br", "li", "div") and not self.ignored:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == self.ignored:
            self.ignored = None

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def parse_page(payload):
    require(isinstance(payload, dict) and type(payload.get("retcode")) is int, "invalid official envelope")
    require(payload["retcode"] == 0, "official API code {}".format(payload["retcode"]))
    data = payload.get("data")
    require(isinstance(data, dict) and type(data.get("iTotal")) is int and data["iTotal"] > 0
            and isinstance(data.get("list"), list) and 0 < len(data["list"]) <= PAGE_SIZE,
            "invalid or empty official list")
    require(data["iTotal"] >= len(data["list"]), "invalid official total")
    return data["list"], data["iTotal"]


def normalize(row, excluded, source="hoyoverse"):
    _, _, channel_id, prefix, news, notice, event = SITES[source]
    require(isinstance(row, dict) and type(row.get("iInfoId")) is int, "missing official ID")
    identifier = prefix + "-" + str(row["iInfoId"])
    require(OFFICIAL_ID.fullmatch(identifier), "invalid official ID")
    stamp = row.get("dtStartTime")
    require(isinstance(stamp, str) and PUBLISH_TIME.fullmatch(stamp), "invalid official publication time")
    published = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
    channels = row.get("sChanId")
    require(isinstance(channels, list) and channels and
            all(isinstance(channel, str) and channel in {news, notice, event} for channel in channels),
            "invalid official category")
    require(isinstance(row.get("sUrl"), str), "missing official URL field")
    if identifier in excluded or row["sUrl"]:
        return identifier, published, None
    title = clean(row.get("sTitle"), 1000)
    html = clean(row.get("sContent"), 300000)
    require(bool(title), "missing official title")
    parser = ArticleText()
    parser.feed(html)
    parser.close()
    plain = "".join(parser.parts).strip()
    category = classify(title, plain)
    if category == "other":
        if event in channels:
            category = "event"
        elif re.search(r"维护|停服", title) and "维护" in plain:
            category = "maintenance"
        elif "更新通知" in title and "预下载" in title:
            category = "version"
        elif "系统优化" in title:
            category = "system"
        elif notice not in channels and not re.search(r"版本内容一览|前瞻特别节目", title):
            return identifier, published, None
    if not eligible(title, plain):
        return identifier, published, None
    summary = SUMMARIES[category]
    window = ACTIVITY_TIME.search(plain) if category in ("event", "signal") else None
    if window:
        label = "调频" if category == "signal" else "活动"
        summary = "{}时段：{} 至 {}（服务器时间）。".format(label, *window.groups())
    item = {
        "id": identifier, "source": source, "source_uid": channel_id,
        "title": " ".join(title.split())[:180], "category": category, "summary": summary,
        "content": [], "images": [], "published_at": published.isoformat(timespec="seconds"),
        "updated_at": None, "source_url": canonical(identifier), "is_pinned": False,
        "content_hash": digest([title, html]), "ingest": "feed",
    }
    validate_record(item)
    return identifier, published, item


def collect(page_limit, interval, excluded, cutoff, current, source="hoyoverse"):
    host, endpoint, channel, *_ = SITES[source]
    items = {}
    first_ids = set()
    seen = set()
    for page in range(1, page_limit + 1):
        if page > 1:
            time.sleep(interval)
        payload = get_json(endpoint, {
            "iChanId": channel, "iPage": page, "iPageSize": PAGE_SIZE, "sLangKey": "zh-cn",
        }, host=host)
        entries, total = parse_page(payload)
        page_ids = set()
        dates = []
        for entry in entries:
            identifier, published, item = normalize(entry, excluded, source)
            require(identifier not in page_ids, "duplicate ID in official page")
            page_ids.add(identifier)
            dates.append(published)
            if item is None or published < cutoff or published > current:
                continue
            if identifier in items:
                require(items[identifier] == item, "conflicting official item during pagination")
            items[identifier] = item
            if page == 1:
                first_ids.add(identifier)
        require(not page_ids <= seen, "official pagination repeated a page")
        seen.update(page_ids)
        if page * PAGE_SIZE >= total or max(dates) < cutoff:
            break
    else:
        print("Official page budget reached; the three-month window may be incomplete")
    require(bool(items), "no eligible official records; archive preserved")
    print("{}: {} pages, {} eligible items".format(source, page, len(items)))
    return items, first_ids
