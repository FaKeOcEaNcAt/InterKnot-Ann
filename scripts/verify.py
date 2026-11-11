from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from scripts.build import OUT, RIGHTS_CONTACT, SOURCES
from scripts.model import BILI_ID, OFFICIAL_ID, ORIGIN, REMOTE_IMAGE, canonical, decode, require

PUBLIC_ASSET = {"site.css", "app.js"}
LINK_ATTR = {"a": "href", "img": "src", "link": "href", "script": "src"}


class Page(HTMLParser):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.has_main = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        require(not any(key.startswith("on") or key == "style" for key in values), "inline executable attribute")
        require(tag not in {"iframe", "embed", "object", "base"}, "unsafe element")
        if tag == "main":
            self.has_main = True
        if tag in LINK_ATTR:
            href = values.get(LINK_ATTR[tag], "")
            if tag == "a" and href == "#main":
                return
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                if tag == "img":
                    require(REMOTE_IMAGE.fullmatch(href) and values.get("referrerpolicy") == "no-referrer",
                            "unsafe remote image")
                    return
                bili = href.startswith(ORIGIN + "/opus/") and BILI_ID.fullmatch(parts.path[6:])
                number = parts.path.rsplit("/", 1)[-1]
                official = OFFICIAL_ID.fullmatch("hoyo-" + number) and href in (
                    canonical("hoyo-" + number), canonical("mihoyo-" + number)
                )
                require(tag == "a" and (href in {url for _, url in SOURCES}
                        or href == RIGHTS_CONTACT
                        or ((bili or official)
                            and not parts.query and not parts.fragment)),
                        "unsafe external URL")
                require("noopener" in values.get("rel", "").split(), "unsafe external link relationship")
            else:
                path = PurePosixPath("index.html" if tag == "a" and href == "index.html?source=all" else href)
                require(href and not path.is_absolute() and ".." not in path.parts
                        and (self.root / path).is_file(), "missing or unsafe local URL")


def verify(out):
    require(out.is_dir(), "missing build output")
    require((out / "index.html").stat().st_size <= 48000, "homepage HTML budget exceeded")
    require((out / "assets" / "app.js").stat().st_size <= 15000, "script budget exceeded")
    require((out / "assets" / "site.css").stat().st_size <= 20000, "style budget exceeded")
    for path in out.rglob("*"):
        require(not path.is_symlink(), "symlink in build")
        if path.is_dir():
            continue
        relative = path.relative_to(out)
        if path.suffix == ".html" and len(relative.parts) == 1:
            parser = Page(out)
            parser.feed(path.read_text(encoding="utf-8"))
            parser.close()
            require(parser.has_main, "missing prerendered main content")
        elif relative.parts[:2] == ("assets", "media"):
            require(path.suffix in (".jpg", ".png") and len(relative.parts) == 3, "unexpected media")
        else:
            require(relative.parts[0] == "assets" and len(relative.parts) == 2, "unexpected build file")
            if path.name.startswith("search-") and path.suffix == ".json":
                rows = decode(path.read_bytes())
                require(isinstance(rows, list) and len(rows) <= 100, "invalid search index")
            else:
                require(path.name in PUBLIC_ASSET, "unexpected public asset")


if __name__ == "__main__":
    verify(OUT)
    print("Static HTML, links, output allowlist and budgets passed")
