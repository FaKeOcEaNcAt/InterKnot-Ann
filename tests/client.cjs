const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const acorn = require("internal/deps/acorn/acorn/dist/acorn");

const source = fs.readFileSync("static/app.js", "utf8");
acorn.parse(source, { ecmaVersion: 5 });
assert.doesNotMatch(source, /\b(?:eval|fetch|Promise|Map|Set|innerHTML|outerHTML|querySelector)\b/);

function element() {
    return {
        textContent: "",
        children: [],
        events: {},
        appendChild(child) { this.children.push(child); },
        addEventListener(name, callback) { this.events[name] = callback; },
        removeAttribute() { this.revealed = true; },
        getAttribute() { return "1"; },
    };
}

function runtime(fullscreen, storage = {}, reduced = false, userAgent = "Windows Phone 8.1", regional = {}) {
    const ids = {};
    for (const id of ["screen", "screen-status", "search", "search-status", "results", "query", "category",
        "background-motion", "motion-setting", "source-settings"]) {
        ids[id] = element();
    }
    const root = element();
    root.className = "";
    const document = {
        ...element(), documentElement: root,
        getElementById(id) { return ids[id]; },
        getElementsByTagName() { return []; },
        createElement: element,
        createDocumentFragment: element,
    };
    if (fullscreen) {
        root.msRequestFullscreen = function () { document.msFullscreenElement = root; };
        document.msExitFullscreen = function () { delete document.msFullscreenElement; };
    }
    const requested = [];
    function XMLHttpRequest() {
        this.open = (method, url) => requested.push([method, url]);
        this.send = () => {
            this.status = 200;
            this.responseText = JSON.stringify([
                ["1254117990746554369", "<img>中文标题", "event", "活动摘要", "2026-10-01 14:18", "附加关键词"],
                ["../../outside", "关键词", "event", "", "", ""],
            ]);
            this.onload();
        };
    }
    const window = {
        matchMedia() { return { matches: reduced }; },
        localStorage: { getItem(key) { return storage[key]; }, setItem(key, value) { storage[key] = value; } },
    };
    const redirects = [];
    if (regional.path) {
        window.location = {
            pathname: regional.path, search: regional.query || "", hash: "",
            replace(url) { redirects.push(url); },
        };
    }
    if (regional.zone) {
        window.Intl = { DateTimeFormat() { return { resolvedOptions() { return { timeZone: regional.zone }; } }; } };
    }
    function DeviceDate() { this.getTimezoneOffset = () => regional.offset; }
    vm.runInNewContext(source, { document, XMLHttpRequest, window,
        Date: DeviceDate, navigator: { userAgent, ...regional.languages } });
    return { ids, document, requested, redirects };
}

const { ids, document, requested } = runtime(true);
ids.query.value = "标题 关键词";
ids.category.value = "event";
ids.search.events.submit({ preventDefault() {} });
assert.deepEqual(requested, [["GET", "assets/search-0.json"]]);
const fragment = ids.results.children[0];
assert.equal(fragment.children.length, 1);
assert.equal(fragment.children[0].children[0].textContent, "<img>中文标题");
assert.match(ids["search-status"].textContent, /1 条/);
ids.screen.events.click();
document.events.MSFullscreenChange();
assert.equal(ids.screen.textContent, "退出全屏");
ids.screen.events.click();
document.events.MSFullscreenChange();
assert.equal(ids.screen.textContent, "全屏");
const unsupported = runtime(false).ids;
assert.equal(unsupported.screen.revealed, true);
unsupported.screen.events.click();
assert.match(unsupported["screen-status"].textContent, /无法进入全屏/);
const motionPreference = {};
const motion = runtime(true, motionPreference);
assert.equal(motion.ids["background-motion"].checked, false);
motion.ids["background-motion"].checked = true;
motion.ids["background-motion"].events.change();
assert.match(motion.document.documentElement.className, /motion-background/);
assert.equal(runtime(true, motionPreference).ids["background-motion"].checked, true);
assert.equal(runtime(false, {}, true, "Desktop").ids["background-motion"].checked, false);
assert.equal(runtime(false, {}, false, "Desktop").ids["background-motion"].checked, true);
const home = { path: "/InterKnot-Ann/" };
function feed(regional, storage = {}) {
    return runtime(false, storage, false, "Windows Phone 8.1", { ...home, ...regional }).redirects;
}
assert.deepEqual(feed({ languages: { language: "zh-Hans-CN" }, zone: "America/Vancouver" }), ["index-mihoyo.html"]);
assert.deepEqual(feed({ languages: { languages: ["zh-HK", "zh-CN"] }, zone: "Asia/Shanghai" }), ["index-hoyoverse.html"]);
assert.deepEqual(feed({ languages: { language: "zh-TW" }, offset: -480 }), ["index-hoyoverse.html"]);
assert.deepEqual(feed({ languages: { systemLanguage: "zh" }, offset: -480 }), ["index-mihoyo.html"]);
assert.deepEqual(feed({ languages: { language: "zh" }, zone: "Asia/Singapore" }), ["index-hoyoverse.html"]);
assert.deepEqual(feed({ zone: "Asia/Shanghai" }), ["index-mihoyo.html"]);
assert.deepEqual(feed({}), ["index-hoyoverse.html"]);
assert.deepEqual(feed({ query: "?source=all" }), []);
assert.deepEqual(feed({ path: "/InterKnot-Ann/index-mihoyo.html" }), []);
const feedPreference = {};
const settings = runtime(false, feedPreference, false, "Desktop").ids["source-settings"];
settings.events.click({ target: { getAttribute() { return "bilibili"; } } });
assert.deepEqual(feed({ zone: "Asia/Shanghai" }, feedPreference), ["index-bilibili.html"]);
settings.events.click({ target: { getAttribute() { return "auto"; } } });
assert.deepEqual(feed({ zone: "Asia/Shanghai" }, feedPreference), ["index-mihoyo.html"]);
console.log("ES5 syntax, search, safe DOM output and fullscreen behavior passed");
