import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from scripts import bilibili, build, official, sync
from scripts.model import CST, DATA, REMOTE_IMAGE, UID, Invalid, canonical, decode, digest, load_store, validate_record
from scripts.verify import verify

ID = "1254117990746554369"
NOW = "2026-11-10T12:00:00+08:00"
CUTOFF = datetime(2026, 8, 10, tzinfo=CST)
ARTICLE = "「跛脚乌鸦奇探录」活动说明\n〖活动时间〗\n2026/10/03 10:00"
PUBLISHED = "2026-10-01T14:18:00+08:00"


def detail(body=ARTICLE, identifier=ID, pinned=False):
    return {"id_str": identifier, "type": "DYNAMIC_TYPE_DRAW", "modules": {
        "module_author": {"mid": int(UID), "pub_ts": int(datetime.fromisoformat(PUBLISHED).timestamp())},
        "module_dynamic": {"desc": {"text": body}, "major": {"type": "MAJOR_TYPE_DRAW", "draw": {"items": []}}},
        "module_tag": {"text": "置顶"} if pinned else None,
    }}


def discovery(identifier=ID, body=ARTICLE):
    return {"opus_id": identifier, "jump_url": "//www.bilibili.com/opus/" + identifier,
            "content": body, "author": None, "badge": None, "pub_time": ""}


def envelope(items, offset=None):
    return {"code": 0, "data": {"items": items, "has_more": offset is not None, "offset": offset}}


class CollectTest(unittest.TestCase):
    def test_observed_live_discovery_requires_separate_detail(self):
        sample = Path(__file__).parent / "fixtures" / "opus-discovery.json"
        entries, cursor = bilibili.parse_page(decode(sample.read_bytes()))
        self.assertEqual(bilibili.discovery(entries[0], set()), "1261426740893319168")
        self.assertIsNone(entries[0]["author"])
        self.assertEqual(entries[0]["pub_time"], "")
        self.assertIsNotNone(cursor)

    def test_discovery_schema_based_on_live_list(self):
        self.assertEqual(bilibili.discovery(discovery(), set()), ID)
        self.assertIsNone(bilibili.discovery(discovery(), {ID}))
        self.assertIsNone(bilibili.discovery(discovery(body="互动抽奖\n转发抽奖，参与领取周边"), set()))
        self.assertEqual(bilibili.discovery(discovery(body="互动抽奖 #绝区零#\n" + ARTICLE), set()), ID)

    def test_collect_paginates_deduplicates_and_verifies_author(self):
        other = "1261511783417380880"
        pages = [envelope([discovery()], "123"), envelope([discovery(), discovery(other)])]
        with patch.object(bilibili, "get_page", side_effect=pages) as page, \
                patch.object(bilibili, "get_detail", side_effect=[detail(pinned=True), detail(identifier=other)]) as fetch, \
                patch.object(bilibili.time, "sleep"):
            records, first = bilibili.collect(4, 2, set(), CUTOFF)
        self.assertEqual(page.call_args_list[1].args, ("123",))
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(first, {ID})
        self.assertEqual(records[ID]["published_at"], PUBLISHED)
        self.assertEqual(records[ID]["category"], "event")
        self.assertTrue(records[ID]["is_pinned"])

    def test_schema_changes_partial_data_and_author_mismatch(self):
        for payload in ({"code": -352}, {"code": True}, {"code": 0, "data": {"items": []}},
                        envelope([], "https://evil.invalid/?unsafe")):
            with self.subTest(payload=payload), self.assertRaises(Invalid):
                bilibili.parse_page(payload)
        bad = detail()
        bad["modules"]["module_author"]["mid"] = 42
        with self.assertRaisesRegex(Invalid, "author"):
            bilibili.normalize(bad, set())
        del bad["modules"]["module_author"]
        with self.assertRaisesRegex(Invalid, "missing"):
            bilibili.normalize(bad, set())
        with patch.object(bilibili, "get_json", return_value={"code": -352, "message": "sensitive"}):
            with self.assertRaisesRegex(Invalid, "code -352"):
                bilibili.get_detail(ID)

    def test_repeat_cursor_and_empty_page(self):
        for pages in ([envelope([])], [envelope([discovery()], "123")] * 2):
            with patch.object(bilibili, "get_page", side_effect=pages), \
                    patch.object(bilibili, "get_detail", return_value=detail()), \
                    patch.object(bilibili.time, "sleep"), self.assertRaises(Invalid):
                bilibili.collect(3, 2, set(), CUTOFF)

    def test_date_window_and_classification(self):
        self.assertEqual(bilibili.three_months_ago(datetime(2026, 5, 31, tzinfo=CST)).day, 28)
        self.assertEqual(bilibili.classify("版本活动合集", "仅在标题中提及活动"), "other")
        self.assertEqual(bilibili.classify("3.3版本限时频段（下期）", "调频活动时间见下方。"), "signal")

    def test_redirect_never_followed_and_transport_retries_bounded(self):
        with patch.object(bilibili.http.client, "HTTPSConnection") as connect:
            response = connect.return_value.getresponse.return_value
            response.status = 302
            response.headers = Message()
            response.headers["Location"] = "https://127.0.0.1/private"
            with self.assertRaisesRegex(Invalid, "HTTP 302"):
                bilibili.get_page("")
            self.assertEqual(connect.call_count, 1)
            connect.return_value.close.assert_called_once()
        with patch.object(bilibili, "request_json", side_effect=OSError("private-token")) as request, \
                patch.object(bilibili.time, "sleep") as sleep, redirect_stdout(io.StringIO()) as captured:
            with self.assertRaisesRegex(Invalid, "OSError"):
                bilibili.get_page("")
            self.assertNotIn("private-token", captured.getvalue())
            self.assertEqual(request.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [3, 6])

    def test_feed_media_validation(self):
        major = {"draw": {"items": [
            {"src": "https://i0.hdslb.com/bfs/album/pic.png"},
            {"src": "https://i0.hdslb.com.evil.invalid/bfs/album/pic.png"},
            {"src": "https://i0.hdslb.com@127.0.0.1/bfs/album/pic.png"},
            {"src": "https://i0.hdslb.com/bfs/album/../evil.png"},
            {"src": "javascript:bad"}, {"src": "data:image/png;base64,x"},
        ]}}
        self.assertEqual(bilibili.media_references(major, "MAJOR_TYPE_DRAW"),
                         ["https://i0.hdslb.com/bfs/album/pic.png"])


class ArchiveTest(unittest.TestCase):
    def test_merge_idempotence_edit_pin_and_archive_retention(self):
        starting = {"schema": 1, "last_changed_sync": None, "items": []}
        original = bilibili.normalize(detail(pinned=True), set())
        first = sync.merge(starting, {ID: original}, {ID}, NOW)
        self.assertIs(sync.merge(first, {ID: original}, {ID}, NOW), first)
        edited = bilibili.normalize(detail(ARTICLE + "\n内容修改"), set())
        changed = sync.merge(first, {ID: edited}, {ID}, NOW)
        self.assertEqual(changed["items"][0]["updated_at"], NOW)
        self.assertFalse(changed["items"][0]["is_pinned"])
        self.assertEqual(changed["items"][0]["published_at"], PUBLISHED)
        self.assertIs(sync.merge(changed, {ID: edited}, {ID}, NOW), changed)
        other_id = "1261511783417380880"
        other = bilibili.normalize(detail(identifier=other_id), set())
        self.assertEqual(len(sync.merge(changed, {other_id: other}, {other_id}, NOW)["items"]), 2)

    def test_failed_collection_preserves_archive_and_sanitizes_log(self):
        before = DATA.read_bytes()
        with patch.object(official, "collect", side_effect=ValueError("do not print secret")), \
                patch("sys.argv", ["sync"]), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(sync.main(), 1)
        self.assertEqual(DATA.read_bytes(), before)
        self.assertNotIn("do not print secret", output.getvalue())

    def test_model_dangerous_input(self):
        record = bilibili.normalize(detail(), set())
        for key, value in [
            ("id", "../evil"), ("source_url", "javascript:alert(1)"), ("source_url", "data:text/html,1"),
            ("source_url", "https://www.bilibili.com.evil.invalid/opus/" + ID),
            ("title", "过" * 181), ("title", "\u202e逆向"), ("summary", "\ud800"),
            ("published_at", "2026-10-01"), ("updated_at", "2026-01-01T00:00:00+08:00"),
            ("is_pinned", 1), ("images", [{"file": "../../evil"}]),
        ]:
            with self.subTest(key=key), self.assertRaises(Invalid):
                validate_record(dict(record, **{key: value}))
        for raw in (b"{", b'{"x":NaN}', b'{"x":1,"x":2}', b"\xff"):
            with self.assertRaises(ValueError):
                decode(raw)


class BuildTest(unittest.TestCase):
    def test_prerendered_pagination_images_no_secrets_and_safe_unicode(self):
        store = copy.deepcopy(load_store())
        store["items"] = [record for record in store["items"] if record["source"] == "bilibili"]
        item = store["items"][0]
        item["is_pinned"] = True
        item["title"] = '<img src="x" onerror="alert(1)"> 中文🐈 & 绳网'
        item["content"] = [{"type": "paragraph", "text": "</script><script>bad()</script>"}]
        for index in range(13):
            identifier = str(1261234567890123000 + index)
            store["items"].append(dict(item, id=identifier, source_url=canonical(identifier),
                                       title="中文公告 " + str(index), images=[], is_pinned=False,
                                       content_hash=digest(index)))
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with patch.dict("os.environ", {"GITHUB_TOKEN": "sentinel-token-not-for-publication"}):
                build.render(out, store)
            verify(out)
            home = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("index-2.html", home)
            tabs = home.split('aria-label="公告分类">', 1)[1].split("</nav>", 1)[0]
            self.assertEqual(tabs.count("<a "), 3)
            self.assertIn("category-notice.html", tabs)
            settings = (out / "settings.html").read_text(encoding="utf-8")
            for source in ("bilibili", "mihoyo", "hoyoverse"):
                self.assertIn("index-" + source + ".html", settings)
            source_home = (out / "index-bilibili.html").read_text(encoding="utf-8")
            self.assertIn("category-event-bilibili.html", source_home)
            self.assertIn("category-event-2.html", (out / "category-event.html").read_text(encoding="utf-8"))
            article = (out / build.article_path(item)).read_text(encoding="utf-8")
            self.assertIn("&lt;img", article)
            self.assertIn("&lt;/script&gt;", article)
            self.assertIn("中文🐈 &amp; 绳网", article)
            self.assertIn("<figcaption>", article)
            self.assertIn("-thumb.jpg", home)
            self.assertIn(item["images"][0]["file"], article)
            self.assertNotIn("<script>bad", article)
            self.assertIn(PUBLISHED[:10], (out / ("post-" + ID + ".html")).read_text(encoding="utf-8"))
            for file in out.rglob("*"):
                if file.is_file():
                    self.assertNotIn(b"sentinel-token-not-for-publication", file.read_bytes())

    def test_reject_media_paths_and_bad_binary(self):
        record = next(record for record in load_store()["items"] if record["images"])
        record["images"][0]["file"] = "https://i0.hdslb.com/a.png"
        with self.assertRaisesRegex(Invalid, "image path"):
            validate_record(record)
        with self.assertRaisesRegex(Invalid, "invalid PNG"):
            build.dimensions("fake.png", b"<html>not an image</html>")

    def test_reviewed_cdn_image_markup_and_policy(self):
        safe = "https://i0.hdslb.com/bfs/new_dyn/sample.jpg"
        self.assertTrue(REMOTE_IMAGE.fullmatch(safe + "@480w.jpg"))
        for url in (safe + "?x=1", safe.replace("i0.hdslb.com", "i0.hdslb.com.evil"),
                    safe.replace("sample.jpg", "sample.svg"), safe.replace("/bfs/", "/bfs/../")):
            self.assertIsNone(REMOTE_IMAGE.fullmatch(url))
        html = build.remote_figure({"url": safe, "thumbnail": safe + "@480w.jpg", "caption": "<图注>"},
                                   cover=True, fallback="cover.jpg")
        self.assertIn('data-fallback="assets/media/cover.jpg"', html)
        self.assertIn('referrerpolicy="no-referrer"', html)


class OfficialTest(unittest.TestCase):
    def test_official_fixture_normalizes_channels_and_does_not_publish_markup(self):
        sample = Path(__file__).parent / "fixtures" / "hoyoverse-list.json"
        rows, total = official.parse_page(decode(sample.read_bytes()))
        identifier, stamp, record = official.normalize(rows[0], set())
        self.assertEqual(total, 1584)
        self.assertEqual(identifier, "hoyo-167271")
        self.assertEqual(record["source_url"], "https://zenless.hoyoverse.com/zh-cn/news/167271")
        self.assertEqual(stamp.isoformat(), "2026-11-09T14:30:00+08:00")
        self.assertEqual(record["category"], "event")
        self.assertIn("2026/12/01 03:59", record["summary"])
        self.assertNotIn("script", repr(record))
        cn_row = dict(rows[0], iInfoId=161243, sChanId=["279"])
        _, _, cn = official.normalize(cn_row, set(), source="mihoyo")
        self.assertEqual(cn["source"], "mihoyo")
        self.assertEqual(cn["source_url"], "https://zzz.mihoyo.com/news/161243")
        with self.assertRaises(Invalid):
            official.normalize(dict(rows[0], sChanId=["wrong"]), set())
        with self.assertRaises(Invalid):
            official.parse_page({"retcode": 0, "data": {"iTotal": 0, "list": []}})

    def test_official_pagination_uses_cutoff_and_preserves_bilibili_pin(self):
        sample = Path(__file__).parent / "fixtures" / "hoyoverse-list.json"
        page = decode(sample.read_bytes())
        row = page["data"]["list"][0]
        older = dict(row, dtStartTime="2026-08-01 11:00:00", iInfoId=160000)
        second = {"retcode": 0, "data": {"iTotal": 1584, "list": [older]}}
        with patch.object(official, "get_json", side_effect=[page, second]) as get, \
                patch.object(official.time, "sleep"):
            incoming, first = official.collect(4, 2, set(), CUTOFF, datetime.fromisoformat(NOW))
        self.assertEqual([call.args[1]["iPage"] for call in get.call_args_list], [1, 2])
        self.assertEqual(set(incoming), {"hoyo-167271"})
        bili = bilibili.normalize(detail(pinned=True), set())
        store = {"schema": 1, "last_changed_sync": None, "items": [bili]}
        merged = sync.merge(store, incoming, first, NOW)
        self.assertEqual(len(merged["items"]), 2)
        self.assertTrue(next(item for item in merged["items"] if item["id"] == ID)["is_pinned"])
        self.assertIs(sync.merge(merged, incoming, first, NOW), merged)


if __name__ == "__main__":
    unittest.main()
