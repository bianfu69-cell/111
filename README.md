# 📡 Dynabook G83 雅虎日拍捡漏雷达（适配日淘任意门）

专为淘 **东芝 / Dynabook G83（13代主力 + 12代/11代白菜捡漏）** 打造的雅虎日拍实时监控工具，**纯 Python 零第三方依赖**，同时支持：
1. **本地网页排行榜 + 后台自动盯盘 + Windows 桌面通知**
2. **手机微信 / Bark / 飞书 / 钉钉 / ntfy 自动推送**
3. **GitHub Actions 免费 24 小时云端挂机 + GitHub Pages 手机随时看榜单**

---

## 核心特性
- **直接读取雅虎日拍结构化数据**：自动按笔记本整机分类（`auccat=23412`）抓取，排除电源/电池/键盘/故障机/拆机件。
- **真实落地总价自动换算**：
  - 自动区分 **商家含 10% 消费税** vs **个人免税卖家**（不会重复算税）；
  - 自动拉取实时日元汇率并加上任意门汇损估算、代拍费（300円）、日内运费、EMS 国际运费+加固（4500円）；
  - 对 `16GB + 256GB` 自动加 **¥180 换盘差价** 算出 **「折合 512GB 等效到手价」**，跟闲鱼 512G 行情（如 13 代 ¥2,400）直接横向比价；
  - 同时标出 **若被海关抽税 (+13%) 的封顶价**。
- **默认各代捡漏目标线（可在网页里随时改）**：
  - **13代**（`G83/LY` / `G83/LW`，`1340P` / `1334U` / `1345U`）：折合 512G ≤ **¥2,000**（对比闲鱼 ¥2,400）
  - **12代**（`G83/KW` / `G83/KV` / `G83/KY`）：折合 512G ≤ **¥1,450**（超值才考虑）
  - **11代**（`G83/HU` / `G83/HS`）：折合 512G ≤ **¥1,000**（真白菜才考虑）
- **一键直达日淘任意门**：每个商品同时提供「🚀 去任意门」「🔗 雅虎原页」「📋 复制链接（粘贴到任意门 App 搜索框直达）」。

---

## 用法一：Windows 本地一键启动（网页看板 + 自动巡检）

直接双击项目目录下的 **`启动雷达.bat`**，或在终端运行：

```bash
python server.py
```

浏览器会自动打开 **`http://127.0.0.1:8783`**，后台默认每 **10 分钟** 自动刷新一次雅虎日拍。

---

## 用法二：3 分钟配置手机自动推送（不用盯着看）

在本地网页右上角点 **「⚙️ 预算与推送设置」**，填任意一个推送通道并点 **「📤 发送测试推送」**：

- **微信推送（最推荐：PushPlus，免费）**：
  1. 微信打开 [pushplus.plus](https://www.pushplus.plus/) 扫码登录并关注公众号；
  2. 复制你的 `Token`，填进「微信 PushPlus Token」保存即可。
- **iPhone 推送（最优雅：Bark，免费）**：
  1. App Store 下载 **Bark**；
  2. 复制 App 里的推送 URL（形如 `https://api.day.app/你的Key`）填进去，收到推送点一下直接跳进任意门看机。
- **安卓 / iOS 通用免注册（ntfy，免费）**：
  1. 手机装开源 App **ntfy**，随便订阅一个自己起的不重复主题名（如 `g83-radar-9527`）；
  2. 把同一个主题名填到「ntfy 主题名」即可。
- 同时也支持 **Server酱、飞书机器人、钉钉机器人、Telegram**。

---

## 用法三：免费白嫖 GitHub Actions 24 小时云端盯盘 + 手机看排行榜

电脑关机也能每 15 分钟自动扫一次，发现好价直接微信/Bark 推给你，手机浏览器还能直接打开排行榜：

1. 在 GitHub 新建一个仓库（Public 可免费开 GitHub Pages；Private 也可以跑推送），把本项目所有文件推送上去：
   ```bash
   git init
   git add .
   git commit -m "init g83 yahoo radar"
   git branch -M main
   git remote add origin https://github.com/你的用户名/g83-yahoo-radar.git
   git push -u origin main
   ```
2. 打开仓库的 **Settings → Secrets and variables → Actions → New repository secret**，添加你的推送密钥（任选其一即可）：
   - `PUSHPLUS_TOKEN`（微信 PushPlus）
   - `BARK_URL`（iPhone Bark）
   - `SERVERCHAN_KEY` / `FEISHU_WEBHOOK` / `DINGTALK_WEBHOOK` / `NTFY_TOPIC`
3. 打开仓库 **Actions** 页面，手动点一次 **`G83 Yahoo Radar 24x7 Monitor` → `Run workflow`** 测试。
4. （可选）打开仓库 **Settings → Pages**，Source 选 **`Deploy from a branch`**，Branch 选 **`main` / `/docs`** 保存。1 分钟后你就能在手机浏览器随时打开 `https://你的用户名.github.io/g83-yahoo-radar/` 看实时更新的 G83 排行榜！
