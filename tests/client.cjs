const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const acorn = require("internal/deps/acorn/acorn/dist/acorn");

const source = fs.readFileSync("static/app.js", "utf8");
acorn.parse(source, { ecmaVersion: 5 });
assert.doesNotMatch(source, /\b(?:eval|fetch|Promise|Map|Set|innerHTML|outerHTML|localStorage|querySelector)\b/);

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

function runtime(fullscreen) {
    const ids = {};
    for (const id of ["screen", "screen-status", "search", "search-status", "results", "query", "category"]) {
        ids[id] = element();
    }
    const root = element();
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
    vm.runInNewContext(source, { document, XMLHttpRequest, navigator: { userAgent: "Windows Phone 8.1" } });
    return { ids, document, requested };
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
console.log("ES5 syntax, search, safe DOM output and fullscreen behavior passed");
