(function () {
    "use strict";
    var root = document.documentElement;
    var screen = document.getElementById("screen");
    var screenStatus = document.getElementById("screen-status");
    var request = root.requestFullscreen || root.msRequestFullscreen || root.webkitRequestFullscreen;
    var exit = document.exitFullscreen || document.msExitFullscreen || document.webkitExitFullscreen;
    var windowsPhone = /Windows Phone/i.test(navigator.userAgent);
    if (windowsPhone) {
        root.className += " windows-phone";
    }

    function isFullscreen() {
        return document.fullscreenElement || document.msFullscreenElement || document.webkitFullscreenElement;
    }

    function screenError() {
        screenStatus.textContent = "当前浏览器无法进入全屏。可继续使用公告页面。";
    }

    function updateScreen() {
        screen.textContent = isFullscreen() ? "退出全屏" : "全屏";
        screenStatus.textContent = "";
    }

    if ((request && exit) || windowsPhone) {
        screen.removeAttribute("hidden");
        screen.addEventListener("click", function () {
            var result;
            if (!request || !exit) {
                screenError();
                return;
            }
            try {
                result = isFullscreen() ? exit.call(document) : request.call(root);
                if (result && typeof result.then === "function") {
                    result.then(null, screenError);
                }
            } catch (error) {
                screenError();
            }
        });
        document.addEventListener("fullscreenchange", updateScreen);
        document.addEventListener("MSFullscreenChange", updateScreen);
        document.addEventListener("webkitfullscreenchange", updateScreen);
        document.addEventListener("fullscreenerror", screenError);
        document.addEventListener("MSFullscreenError", screenError);
        document.addEventListener("webkitfullscreenerror", screenError);
    }

    var media = document.getElementsByTagName("img");
    var index;
    function imageFallback(event) {
        var target = event.target;
        if (target.tagName === "IMG") {
            var fallback = target.getAttribute("data-fallback");
            if (fallback) {
                target.removeAttribute("data-fallback");
                target.setAttribute("src", fallback);
                return;
            }
            target.parentNode.className += " unavailable";
            target.setAttribute("hidden", "");
        }
    }
    document.addEventListener("error", imageFallback, true);
    for (index = 0; index < media.length; index += 1) {
        if (media[index].complete && media[index].naturalWidth === 0) {
            imageFallback({ target: media[index] });
        }
    }

    var form = document.getElementById("search");
    if (!form) {
        return;
    }

    var resultList = document.getElementById("results");
    var status = document.getElementById("search-status");
    var shardCount = Number(form.getAttribute("data-shards"));
    var active = null;
    var generation = 0;
    var limit = 100;

    function resultNode(row) {
        var item = document.createElement("li");
        var link = document.createElement("a");
        var description = document.createElement("p");
        link.href = "post-" + row[0] + ".html";
        link.textContent = row[1];
        description.textContent = row[4] + (row[6] ? " · " + row[6] : "") + " · " + row[3];
        item.appendChild(link);
        item.appendChild(description);
        return item;
    }

    form.removeAttribute("hidden");
    form.addEventListener("submit", function (event) {
        event.preventDefault();
        generation += 1;
        if (active) {
            active.abort();
        }
        var current = generation;
        var query = document.getElementById("query").value.toLowerCase().trim();
        var terms = query ? query.split(/\s+/) : [];
        var category = document.getElementById("category").value;
        var count = 0;
        resultList.textContent = "";
        status.textContent = "正在检索归档…";

        function searchFailed() {
            if (current === generation) {
                active = null;
                status.textContent = "搜索索引暂时无法读取。你仍可通过分类浏览。";
            }
        }

        function load(part) {
            if (part >= shardCount) {
                active = null;
                status.textContent = "找到 " + count + " 条公告" + (count > limit ? "，显示前 " + limit + " 条。" : "。");
                return;
            }
            var xhr = new XMLHttpRequest();
            active = xhr;
            xhr.open("GET", "assets/search-" + part + ".json", true);
            xhr.timeout = 10000;
            xhr.onerror = searchFailed;
            xhr.ontimeout = searchFailed;
            xhr.onload = function () {
                if (current !== generation) {
                    return;
                }
                if (xhr.status !== 200) {
                    searchFailed();
                    return;
                }
                var rows;
                try {
                    rows = JSON.parse(xhr.responseText);
                    if (!Array.isArray(rows)) {
                        searchFailed();
                        return;
                    }
                } catch (error) {
                    searchFailed();
                    return;
                }
                var fragment = document.createDocumentFragment();
                rows.forEach(function (row) {
                    if (!Array.isArray(row) || !/^(?:[1-9][0-9]{14,21}|(?:hoyo|mihoyo)-[1-9][0-9]{3,11})$/.test(row[0]) ||
                            (category && row[2] !== category)) {
                        return;
                    }
                    var text = [row[1], row[3], row[5]].join(" ").toLowerCase();
                    if (terms.every(function (term) { return text.indexOf(term) !== -1; })) {
                        count += 1;
                        if (count <= limit) {
                            fragment.appendChild(resultNode(row));
                        }
                    }
                });
                resultList.appendChild(fragment);
                load(part + 1);
            };
            xhr.send();
        }

        load(0);
    });
}());
