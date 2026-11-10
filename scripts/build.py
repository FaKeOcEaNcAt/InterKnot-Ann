import os
import re
import shutil
import struct
import tempfile
from html import escape
from string import Template

from scripts.model import CATEGORIES, CST, ROOT, SOURCE_LABELS, date, encoded, load_store, require, reviewed_media

PAGE_SIZE = 12
SEARCH_SIZE = 100
FEED_TABS = (("all", "全部"), ("notice", "公告"), ("event", "活动"))
OUT = ROOT / "_site"
SOURCES = (
    ("Bilibili · 绝区零", "https://space.bilibili.com/1636034895"),
    ("绝区零官网 · 米哈游", "https://zzz.mihoyo.com/news"),
    ("绝区零官网 · HoYoverse", "https://zenless.hoyoverse.com/zh-cn/news"),
)
TEMPLATE = Template((ROOT / "templates" / "page.html").read_text(encoding="utf-8"))


def local(path, label, attrs=""):
    return '<a href="{}"{}>{}</a>'.format(escape(path, quote=True), attrs, escape(label))


def external(url, label):
    return local(url, label, ' class="external" rel="noopener noreferrer"')


def clock(stamp):
    return date(stamp).astimezone(CST).strftime("%Y-%m-%d %H:%M")


def time_tag(stamp):
    return '<time datetime="{}">{}</time>'.format(escape(stamp, quote=True), clock(stamp))


def hero(title, english, description):
    return (
        '<section class="hero"><p class="eyebrow"><i></i> NEW ERIDU / PUBLIC RELAY</p>'
        '<h1>{}</h1><p class="hero-note">{}</p><span class="hero-code" aria-hidden="true">{}</span>'
        '</section>'
    ).format(escape(title), escape(description), escape(english))


def article_path(item):
    return "post-" + item["id"] + ".html"


def list_path(category, page=1, source=None):
    stem = "index" if category == "all" else "category-" + category
    if source:
        stem += "-" + source
    return stem + ".html" if page == 1 else stem + "-" + str(page) + ".html"


def tabs(selected, source=None):
    if selected in CATEGORIES and selected != "event":
        selected = "notice"
    return '<nav class="filters" aria-label="公告分类">{}</nav>'.format("".join(
        local(list_path(key, source=source), label, ' aria-current="page"' if selected == key else "")
        for key, label in FEED_TABS
    ))


def figure(image, cover=False):
    asset = image["thumbnail"] if cover else image["file"]
    size = image["thumbnail_size"] if cover else image["size"]
    caption = "" if cover else "<figcaption>{}</figcaption>".format(escape(image["caption"]))
    return '<figure class="{}"><img src="assets/media/{}" width="{}" height="{}" loading="lazy" decoding="async" alt="{}">{}</figure>'.format(
        "cover-image" if cover else "body-image", escape(asset, quote=True), *size,
        "" if cover else escape(image["caption"], quote=True), caption,
    )


def remote_figure(image, cover=False, fallback=None):
    url = image["thumbnail"] if cover else image["url"]
    attrs = ' data-fallback="assets/media/{}"'.format(escape(fallback, quote=True)) if fallback else ""
    caption = "" if cover else "<figcaption>{}</figcaption>".format(escape(image["caption"]))
    return ('<figure class="{} remote-image"><img src="{}"{} loading="lazy" decoding="async" '
            'referrerpolicy="no-referrer" alt="{}">{}</figure>').format(
        "cover-image" if cover else "body-image", escape(url, quote=True), attrs,
        "" if cover else escape(image["caption"], quote=True), caption,
    )


def card(item, remote):
    key = item["category"]
    category, english = CATEGORIES[key]
    pin = '<span class="pin">置顶</span>' if item["is_pinned"] else ""
    if item["id"] in remote:
        fallback = item["images"][0]["thumbnail"] if item["images"] else None
        cover = remote_figure(remote[item["id"]], cover=True, fallback=fallback)
    elif item["images"]:
        cover = figure(item["images"][0], cover=True)
    else:
        cover = (
            '<div class="cover-art" aria-hidden="true"><span>IK / {}</span>'
            '<strong>{}</strong><i></i></div>'
        ).format(item["id"][-4:], english)
    return (
        '<li class="card card-{}"><a class="card-link" href="{}"><div class="cover">{}{}'
        '<span class="cover-label" aria-hidden="true">{}</span></div>'
        '<div class="card-copy"><p class="byline"><b aria-hidden="true">···</b> {}</p>'
        '<h2>{}</h2><p class="summary">{}</p><p class="card-meta">{} <span>{}</span></p></div></a></li>'
    ).format(key, article_path(item), cover, pin, category, SOURCE_LABELS[item["source"]],
             escape(item["title"]), escape(item["summary"]),
             time_tag(item["published_at"]), category)


def listing(items, category, page, pages, remote, source=None):
    title = {"all": "绳网公告", "notice": "公告"}.get(category)
    if title is None:
        title = CATEGORIES[category][0]
    content = '<ul class="cards">{}</ul>'.format("".join(card(item, remote) for item in items)) if items else (
        '<p class="empty">这个分类暂无已归档的公告。</p>'
    )
    pagination = []
    if page > 1:
        pagination.append(local(list_path(category, page - 1, source), "‹ 上一页"))
    pagination.append("<span>第 {} / {} 页</span>".format(page, pages))
    if page < pages:
        pagination.append(local(list_path(category, page + 1, source), "下一页 ›"))
    body = (
        '<div class="feed-head"><h1><i aria-hidden="true"></i> {}</h1>{}</div>'.format(
            SOURCE_LABELS[source] if source else title, tabs(category, source)
        )
        + content + '<nav class="pagination" aria-label="公告分页">{}</nav>'.format("".join(pagination))
    )
    return title, body


def detail(item, newer, older, remote):
    category = CATEGORIES[item["category"]][0]
    metadata = time_tag(item["published_at"]) + " 北京时间"
    if item["updated_at"]:
        metadata += " · 站点检测到变更 " + time_tag(item["updated_at"])
    blocks = []
    for block in item["content"]:
        tag = "h2" if block["type"] == "heading" else "p"
        blocks.append("<{0}>{1}</{0}>".format(tag, escape(block["text"])))
    if not blocks:
        blocks.append("<p>请打开官方原文查看详情及原配图。</p>")
    for image in reversed(sorted(item["images"], key=lambda image: image["after_block"])):
        blocks.insert(image["after_block"], figure(image))
    if item["id"] in remote:
        blocks.insert(0, remote_figure(remote[item["id"]]))
    neighbors = []
    if newer:
        neighbors.append(local(article_path(newer), "‹ 较新：" + newer["title"], ' rel="prev"'))
    if older:
        neighbors.append(local(article_path(older), "较早：" + older["title"] + " ›", ' rel="next"'))
    return (
        '<p class="breadcrumbs">{} <span aria-hidden="true">/</span> {}</p>'
        '<article class="reader"><p class="eyebrow"><i></i> OFFICIAL RELAY / {}</p><h1>{}</h1>'
        '<p class="reader-meta">{} · {} · {}</p>'
        '<section class="article-copy"><h2>公告摘要</h2><p class="lead">{}</p>{}</section>'
        '<p>{}</p></article><nav class="neighbors" aria-label="相邻公告">{}</nav>'
    ).format(local(list_path("all", source=item["source"]), "‹ 返回该来源"), local(list_path("event" if item["category"] == "event" else "notice", source=item["source"]), category),
             item["id"].rsplit("-", 1)[-1], escape(item["title"]), SOURCE_LABELS[item["source"]], category, metadata,
             escape(item["summary"]), "".join(blocks), external(item["source_url"], "查看官方原文 ↗"),
             "".join(neighbors))


def search(shards):
    options = '<option value="">所有分类</option>' + "".join(
        '<option value="{}">{}</option>'.format(key, category) for key, (category, _) in CATEGORIES.items()
    )
    return (
        hero("搜索与分类", "ARCHIVE SEARCH", "用标题或关键词检索已归档的公告") + tabs(None)
        + '<section class="reader search-panel"><h2>搜索档案</h2>'
        '<form id="search" data-shards="{}" hidden><label for="query">标题或关键词</label>'
        '<input id="query" maxlength="100" type="text" placeholder="例如：版本更新">'
        '<label for="category">分类</label><select id="category">{}</select>'
        '<button class="external" type="submit">搜索</button></form>'
        '<noscript><p>关键词搜索需要 JavaScript。上面的分类和历史分页可直接浏览。</p></noscript>'
        '<p id="search-status" role="status"></p><ol id="results"></ol></section>'
    ).format(shards, options)


def about():
    return (
        hero("站点说明", "FIELD NOTES", "来源、归档范围与非官方声明")
        + '<article class="reader"><h2>关于绳网档案</h2>'
        '<p>本站是玩家制作的《绝区零》公告阅读工具，与米哈游、HoYoverse 及 Bilibili 无隶属关系。</p>'
        '<p>公告来自《绝区零》官网及 Bilibili 官方账号的历史归档。每条记录均标明来源，具体内容与活动时限以原文为准。'
        '页面显示北京时间。部分条目仅提供简要导读和原文入口。</p><h2>官方渠道</h2><ul>{}</ul></article>'
    ).format("".join("<li>{}</li>".format(external(url, label)) for label, url in SOURCES))


def settings_page():
    links = [local("index.html", "综合推送", ' class="external"')]
    links.extend(local(list_path("all", source=source), label, ' class="external"')
                 for source, label in SOURCE_LABELS.items())
    return (hero("设置", "SETTINGS", "切换公告推送的来源")
            + '<section class="reader"><h2>信息源</h2><ul class="source-links">{}</ul></section>'.format(
                "".join("<li>{}</li>".format(link) for link in links)))


def page_html(title, body, selected, sync):
    nav = "".join(local(path, label, ' aria-current="page"' if path == selected else "") for path, label in (
        ("index.html", "公告推送"), ("search.html", "搜索档案"), ("about.html", "站点说明")
    ))
    return TEMPLATE.substitute(title=escape(title), body=body, nav=nav, sync=sync)


def write_page(out, path, title, body, selected, sync):
    (out / path).write_text(page_html(title, body, selected, sync), encoding="utf-8")


def publish_media(out, items):
    # Files come from the reviewed repository only. No remote requests occur during build.
    source = ROOT / "media"
    destination = out / "assets" / "media"
    for item in items:
        for image in item["images"]:
            for file_key, size_key, limit in (("file", "size", 350000), ("thumbnail", "thumbnail_size", 55000)):
                name = image[file_key]
                path = source / name
                require(not source.is_symlink() and not path.is_symlink() and path.is_file(), "missing reviewed image")
                with path.open("rb") as file:
                    raw = file.read(limit + 1)
                require(len(raw) <= limit, "image byte limit exceeded")
                require(dimensions(name, raw) == tuple(image[size_key]), "unexpected image format or dimensions")
                destination.mkdir(exist_ok=True)
                (destination / name).write_bytes(raw)


def dimensions(name, raw):
    if name.endswith(".png"):
        require(len(raw) >= 45 and raw[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                and raw.endswith(b"\x00\x00\x00\x00IEND\xaeB\x60\x82"), "invalid PNG")
        return struct.unpack(">II", raw[16:24])
    require(raw.startswith(b"\xff\xd8") and raw.endswith(b"\xff\xd9"), "invalid JPEG")
    pos = 2
    while pos + 4 <= len(raw):
        require(raw[pos] == 255, "invalid JPEG marker")
        while pos < len(raw) and raw[pos] == 255:
            pos += 1
        require(pos + 3 <= len(raw), "truncated JPEG")
        marker = raw[pos]
        length = int.from_bytes(raw[pos + 1:pos + 3], "big")
        require(length >= 2 and pos + length < len(raw), "invalid JPEG segment")
        if marker in (192, 194):
            require(length >= 8, "invalid JPEG frame")
            height, width = struct.unpack(">HH", raw[pos + 4:pos + 8])
            return width, height
        if marker in (217, 218):
            break
        pos += length + 1
    raise ValueError("JPEG frame not found")


def render(out, store):
    assets = out / "assets"
    assets.mkdir()
    for name in ("site.css", "app.js"):
        shutil.copyfile(ROOT / "static" / name, assets / name)
    chronological = sorted(store["items"], key=lambda item: (date(item["published_at"]), item["id"]), reverse=True)
    items = sorted(chronological, key=lambda item: item["is_pinned"], reverse=True)
    remote = reviewed_media()
    publish_media(out, items)
    def topic(item):
        return (re.sub(r"[\W_]+", "", item["title"]).casefold(),
                date(item["published_at"]).astimezone(CST).date())

    official_topics = {topic(item) for item in items if item["source"] == "hoyoverse"}
    visible = [item for item in items if item["source"] == "hoyoverse" or item["is_pinned"]
               or item["id"] in remote or topic(item) not in official_topics]
    stamp = store["last_changed_sync"]
    sync = "最近一次写入归档：" + time_tag(stamp) if stamp else "归档来源：人工核对"
    for category in ("all", "notice", *CATEGORIES):
        scoped = [item for item in visible if category == "all" or item["category"] == category
                  or (category == "notice" and item["category"] != "event")]
        pages = max(1, (len(scoped) + PAGE_SIZE - 1) // PAGE_SIZE)
        for page in range(1, pages + 1):
            title, body = listing(scoped[(page - 1) * PAGE_SIZE:page * PAGE_SIZE], category, page, pages, remote)
            write_page(out, list_path(category, page), title, body, "index.html", sync)
    for source in SOURCE_LABELS:
        for category, _ in FEED_TABS:
            scoped = [item for item in items if item["source"] == source and (
                category == "all" or (item["category"] == "event") == (category == "event"))]
            pages = max(1, (len(scoped) + PAGE_SIZE - 1) // PAGE_SIZE)
            for page in range(1, pages + 1):
                title, body = listing(scoped[(page - 1) * PAGE_SIZE:page * PAGE_SIZE],
                                      category, page, pages, remote, source)
                write_page(out, list_path(category, page, source), title, body, "index.html", sync)
    write_page(out, "settings.html", "设置", settings_page(), "", sync)
    for source in SOURCE_LABELS:
        scoped = [item for item in chronological if item["source"] == source]
        for i, item in enumerate(scoped):
            newer = scoped[i - 1] if i else None
            older = scoped[i + 1] if i + 1 < len(scoped) else None
            write_page(out, article_path(item), item["title"], detail(item, newer, older, remote), "index.html", sync)
    for start in range(0, len(items), SEARCH_SIZE):
        rows = [[item["id"], item["title"], item["category"], item["summary"], clock(item["published_at"]),
                 " ".join(block["text"] for block in item["content"])[:600], SOURCE_LABELS[item["source"]]]
                for item in items[start:start + SEARCH_SIZE]]
        (assets / "search-{}.json".format(start // SEARCH_SIZE)).write_bytes(encoded(rows))
    shards = (len(items) + SEARCH_SIZE - 1) // SEARCH_SIZE
    write_page(out, "search.html", "搜索与分类", search(shards), "search.html", sync)
    write_page(out, "about.html", "站点说明", about(), "about.html", sync)


def main():
    with tempfile.TemporaryDirectory(prefix=".build-", dir=ROOT) as temp:
        stage = ROOT / temp / "site"
        stage.mkdir()
        render(stage, load_store())
        require(not OUT.is_symlink(), "unsafe output path")
        if OUT.exists():
            shutil.rmtree(OUT)
        os.replace(stage, OUT)
    print("Static site built in _site")


if __name__ == "__main__":
    main()
