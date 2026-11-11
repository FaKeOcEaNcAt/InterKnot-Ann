# 绳网公告 · Inter-Knot

《绝区零》非官方公告档案。Python 预生成首页、分类、分页、详情和搜索页面。浏览器直接读取静态 HTML，搜索时才读取本站的索引。Windows Phone 8.1 / IE11 Mobile 是页面实现的最低兼容目标。

默认采集《绝区零》的米哈游国服官网及 HoYoverse 国际站中文频道，保留已核对的 BiliBili 历史公告。通过全屏按钮左侧的「设置」可进入独立来源的推送页，分类和分页继续限定在该来源。详情显示官方原文编号。详见 [验收报告](docs/acceptance.md)。

设置中的「动态背景」会在当前浏览器记住选择。Windows Phone 和启用系统减少动态效果的浏览器默认关闭。

取得公告正文的转载许可后，可把归档 ID 加入 [正文配置](config/full-text-ids.json)，例如国服使用 mihoyo-161243，国际站使用 hoyo- 加官网编号。重新同步后，有正文的条目会在详情页显示纯文字段落。图片及原网页的排版可通过详情页的官方原文链接查看。

## 在本地运行

需要 Python 3.10 或以上。客户端检查使用 Node.js 24，构建和采集无需安装 Python 第三方依赖。

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
node --expose-internals tests/client.cjs
python -m scripts.build
python -m scripts.verify
python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

访问 [本地预览](http://127.0.0.1:8000/index.html)。此回环地址用于开发预览。正式部署启用 HTTPS。停止预览可按 Ctrl+C。

```powershell
python -m scripts.sync --probe
python -m scripts.sync
```

`--probe` 最多检查两页且保持归档原样。正常采集最多扫描 `config/sources.json` 中的 `page_limit` 页，从北京时间往前推三个日历月，已有更早记录继续保留。当前默认适配器为 `hoyoverse-official`，可将其改为 `bilibili-opus` 复查 Bilibili。缺少必要来源字段时整轮失败，可检查日志后重跑。

## 部署到 GitHub Pages

1. 在 GitHub 新建一个空仓库。上传项目源文件，使用 `.gitignore` 排除生成目录、本地截图和测试缓存。通过 Git 推送时可在本目录执行 `git init -b main`、`git add .`、`git commit -m "Initial Inter-Knot site"`，再按 GitHub 提示添加 `origin` 并推送默认分支。
2. 在 Settings → Actions → General 启用 GitHub Actions 和 GitHub 官方 Actions。自动归档需要工作流的 `persist` Job 可以使用 `GITHUB_TOKEN` 向默认分支推送。若默认分支规则阻止该操作，应按仓库权限策略处理，并保持写权限仅授予持久化任务。
3. 在 Settings → Pages 中把 Source 设为 GitHub Actions。Pages 未启用时，工作流会生成可下载的站点产物并跳过发布。GitHub Free 的 Pages 适用于公开仓库，个人私有仓库需要 GitHub Pro，且发布的 Pages 站点可公开访问。配置完成后，在 Actions → Sync and deploy Inter-Knot → Run workflow 选择默认分支并勾选 `build_only`，发布已有档案。Pages 环境可限定为默认分支。
4. 取消勾选 `build_only` 可手动尝试采集。打开 run 的 Summary 和 Build → Synchronize official announcements 查看结果。采集失败、测试失败或归档写入失败时，采集工作流不会部署。默认分支的代码推送会构建并部署仓库中已审核的归档。
5. 默认项目站点地址是 `https://<owner>.github.io/<repository>/`。配置自定义域名时，在 Pages 设置添加并验证域名，按 GitHub 指引设置 DNS，等证书签发后启用 Enforce HTTPS。页面和静态资源使用相对路径。 [Pages 工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) · [管理自定义域名](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)

计划任务默认在每小时第 17、47 分钟 UTC 尝试执行。修改 `.github/workflows/sync-and-deploy.yml` 的 `cron` 可调整频率。GitHub 调度可能延迟。推送由工作流自身的 `GITHUB_TOKEN` 完成，部署仍在同一轮运行中进行。

## 维护内容和数据源

- `data/announcements.json` 保存记录和最近一次写入归档的时间。无变化的成功采集只在 Actions 摘要记录时间。采集失败原因同样在 Actions 摘要中。
- `config/sources.json` 控制适配器、页数预算、请求间隔和需要排除的 ID。官网条目使用 `hoyo-数字`，Bilibili 条目使用原数字 ID。接口变更时更新 `scripts/official.py` 或 `scripts/bilibili.py`，先跑 `--probe`，再更新结构样本和测试。
- 审核完转载许可后，可在 `config/remote-images.json` 按 Bilibili 公告 ID 填入 `url`、`thumbnail` 和 `caption`。浏览器使用 `<img>` 直接向 Bilibili CDN 请求缩略图与正文图。允许 `i0` 至 `i3.hdslb.com` 的 HTTPS JPG/PNG；列表图片失败时优先回退到该条目的本地导读图。仓库默认未启用外链原图。
- 只将有转载许可的公告图片或站点自制图片放入 `media/`。正文图使用 JPEG/PNG，最长边 1600 px，最大 350,000 字节。缩略图最长边 520 px，最大 55,000 字节。在记录的 `images` 填写 `file`、`size`、`thumbnail`、`thumbnail_size`、`caption` 和 `after_block`。尺寸顺序为宽、高，`after_block` 为图片前的正文块数。首张图的缩略图用于列表，详情保留图注。建议重新编码并去除元数据后提交。
- Windows Phone 测试、全屏行为和证书验证见 [兼容性说明](docs/compatibility.md)。更多实现细节见 [架构](docs/architecture.md) 和 [安全说明](docs/security.md)。
