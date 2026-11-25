(() => {
  let isLocalServer = false;
  let snapshot = null;
  let serverMeta = {};
  let fullConfig = null;
  let activeTab = "steals";
  let localMarks = JSON.parse(localStorage.getItem("g83_marks_v1") || "{}");

  const $ = (id) => document.getElementById(id);

  function showToast(msg, duration = 2600) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => el.classList.remove("show"), duration);
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatCountdown(endTs) {
    if (!endTs) return { text: "未知", cls: "", sec: 999999 };
    const sec = Math.max(0, Math.floor(endTs - Date.now() / 1000));
    if (sec <= 0) return { text: "已结拍", cls: "", sec: 0 };
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    const pad = (n) => String(n).padStart(2, "0");
    if (d > 0) return { text: `剩 ${d}天 ${h}小时`, cls: "", sec };
    if (h >= 3) return { text: `剩 ${h}小时${pad(m)}分`, cls: "", sec };
    if (h >= 1) return { text: `剩 ${pad(h)}:${pad(m)}:${pad(s)}`, cls: "soon", sec };
    return { text: `🔥 剩 ${pad(m)}:${pad(s)}`, cls: "urgent", sec };
  }

  function getMark(it) {
    if (isLocalServer) {
      return { starred: !!it.starred, ignored: !!it.ignored };
    }
    const m = localMarks[it.auction_id] || {};
    return { starred: !!m.starred, ignored: !!m.ignored };
  }

  async function toggleMark(auctionId, field) {
    const it = (snapshot?.items || []).find((x) => x.auction_id === auctionId);
    if (!it) return;
    const cur = getMark(it);
    const nextVal = !cur[field];

    if (isLocalServer) {
      try {
        const res = await fetch("/api/mark", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ auction_id: auctionId, [field]: nextVal }),
        });
        const data = await res.json();
        if (data.ok) {
          it.starred = data.mark.starred;
          it.ignored = data.mark.ignored;
        }
      } catch (e) {
        showToast("保存标记失败: " + e.message);
      }
    } else {
      localMarks[auctionId] = { ...cur, [field]: nextVal };
      localStorage.setItem("g83_marks_v1", JSON.stringify(localMarks));
    }
    showToast(field === "starred" ? (nextVal ? "⭐ 已加入我的盯盘" : "已取消盯盘") : (nextVal ? "✕ 已屏蔽该商品" : "已恢复显示"));
    render();
  }

  function getTabFilteredBase(items, tab) {
    const nowSec = Math.floor(Date.now() / 1000);
    const alive = items.filter((it) => {
      const m = getMark(it);
      if (m.ignored) return false;
      if (it.end_ts && it.end_ts < nowSec - 60) return false;
      return true;
    });

    if (tab === "all") return alive;
    if (tab === "starred") return alive.filter((it) => getMark(it).starred);

    const clean = alive.filter((it) => !it.is_junk && !it.has_severe_defect && it.cpu_tier !== "i3");
    if (tab === "steals") {
      return clean.filter((it) => [14, 13, 12, 11].includes(it.generation));
    }
    if (tab === "gen13") {
      return clean.filter((it) => it.generation === 13 || it.generation === 14);
    }
    if (tab === "ending") {
      return clean.filter((it) => {
        const rem = it.end_ts ? it.end_ts - nowSec : it.remaining_sec;
        return rem > 0 && rem <= 10800;
      });
    }
    if (tab === "buynow") {
      return clean.filter((it) => it.buy_now_price_jpy && it.buy_now_effective_512_cny);
    }
    if (tab === "value1112") {
      return clean.filter((it) => it.generation === 12 || it.generation === 11);
    }
    return clean;
  }

  function render() {
    if (!snapshot || !Array.isArray(snapshot.items)) {
      $("itemList").innerHTML = `<div class="empty-state">暂无扫描数据，点击右上角「立即扫描」开始抓取雅虎日拍！</div>`;
      return;
    }

    const items = snapshot.items;
    const sum = snapshot.summary || {};

    // KPIs
    $("kpiClean").textContent = sum.total_clean ?? items.length;
    $("kpiRaw").textContent = `抓 ${sum.total_raw ?? 0} 条 · 正文深查 ${sum.detail_inspected_count ?? 0} 台 · 拦截硬伤 ${sum.severe_caught_count ?? 0} 台`;
    $("kpiUnderBudget").textContent = sum.under_budget_count ?? 0;
    $("kpiEndingSoon").textContent = sum.ending_soon_count ?? 0;
    $("kpiGenSplit").textContent = `${sum.gen13_count ?? 0} / ${sum.gen12_count ?? 0} / ${sum.gen11_count ?? 0}`;
    $("kpiFx").textContent = snapshot.fx_effective ? snapshot.fx_effective.toFixed(4) : "-";
    const cfgPub = snapshot.config_public || {};
    const cm = cfgPub.cost_model || {};
    const gr = cfgPub.generation_rules || {};
    $("kpiFxSub").textContent = `基准 ${snapshot.fx_base || "-"} + ${cm.fx_spread_pct ?? 3.5}%汇损 · EMS ${cm.intl_shipping_jpy ?? 4500}円`;
    $("kpiBudgetDesc").textContent = `13代≤¥${gr["13"]?.max_effective_512_cny ?? 2000} · 12代≤¥${gr["12"]?.max_effective_512_cny ?? 1450} · 11代≤¥${gr["11"]?.max_effective_512_cny ?? 1000}`;

    // Status line
    let nextStr = "";
    if (isLocalServer && serverMeta.next_scan_ts) {
      const leftMin = Math.max(0, Math.ceil((serverMeta.next_scan_ts - Date.now() / 1000) / 60));
      nextStr = serverMeta.scanning ? " · 正在后台扫描中..." : ` · 约 ${leftMin} 分钟后自动刷新`;
    }
    $("statusSub").textContent = `上次更新: ${snapshot.scanned_at} (耗时 ${snapshot.duration_sec}s)${nextStr}`;

    // Tab counts
    const ram16Filter = (arr) => arr.filter((x) => x.ram_gb && x.ram_gb >= 16);
    $("cntSteals").textContent = ram16Filter(getTabFilteredBase(items, "steals")).length;
    $("cntGen13").textContent = ram16Filter(getTabFilteredBase(items, "gen13")).length;
    $("cntEnding").textContent = ram16Filter(getTabFilteredBase(items, "ending")).length;
    $("cntBuyNow").textContent = ram16Filter(getTabFilteredBase(items, "buynow")).length;
    $("cntValue").textContent = ram16Filter(getTabFilteredBase(items, "value1112")).length;
    $("cntStarred").textContent = getTabFilteredBase(items, "starred").length;
    $("cntAll").textContent = getTabFilteredBase(items, "all").length;

    // Apply tab + filter controls
    let filtered = getTabFilteredBase(items, activeTab);
    const q = $("filterSearch").value.trim().toLowerCase();
    const fGen = $("filterGen").value;
    const fRam = $("filterRam").value;
    const fSsd = $("filterSsd").value;
    const fSeller = $("filterSeller").value;
    const onlyBudget = $("chkUnderBudget").checked;
    const hideDefect = $("chkHideDefect").checked;
    const onlyInspected = $("chkOnlyInspected").checked;

    if (q) {
      filtered = filtered.filter((it) =>
        (it.title + " " + it.cpu_model + " " + it.gen_label_short + " " + it.auction_id).toLowerCase().includes(q)
      );
    }
    if (fGen === "13plus") filtered = filtered.filter((it) => it.generation === 13 || it.generation === 14);
    else if (fGen === "12") filtered = filtered.filter((it) => it.generation === 12);
    else if (fGen === "11") filtered = filtered.filter((it) => it.generation === 11);

    if (activeTab !== "all" && activeTab !== "starred" && fRam === "16plus") {
      filtered = filtered.filter((it) => it.ram_gb && it.ram_gb >= 16);
    }
    if (fSsd === "512plus") filtered = filtered.filter((it) => it.ssd_gb && it.ssd_gb >= 512);
    else if (fSsd === "256") filtered = filtered.filter((it) => it.ssd_gb === 256);

    if (fSeller === "personal") filtered = filtered.filter((it) => !it.is_store);
    else if (fSeller === "store") filtered = filtered.filter((it) => it.is_store);

    if (onlyBudget) filtered = filtered.filter((it) => it.under_budget || it.buy_now_under_budget);
    if (hideDefect) filtered = filtered.filter((it) => !it.has_defect && !it.has_severe_defect && !it.is_junk);
    if (onlyInspected) filtered = filtered.filter((it) => !!it.detail_inspected);

    // Sorting
    const sortBy = $("sortBy").value;
    filtered.sort((a, b) => {
      if (activeTab === "buynow" && sortBy === "score") {
        return (a.buy_now_effective_512_cny ?? 99999) - (b.buy_now_effective_512_cny ?? 99999);
      }
      if (activeTab === "ending" && sortBy === "score") {
        return (a.end_ts || 9e12) - (b.end_ts || 9e12);
      }
      if (sortBy === "eff512") return a.effective_512_cny - b.effective_512_cny;
      if (sortBy === "untaxed") return a.untaxed_cny - b.untaxed_cny;
      if (sortBy === "ending") return (a.end_ts || 9e12) - (b.end_ts || 9e12);
      if (sortBy === "savings") return b.savings_vs_ref_cny - a.savings_vs_ref_cny;
      return b.steal_score - a.steal_score || a.effective_512_cny - b.effective_512_cny;
    });

    $("resultCount").textContent = `当前筛选共 ${filtered.length} 台机器`;

    if (!filtered.length) {
      $("itemList").innerHTML = `<div class="empty-state">当前筛选条件下暂无符合机器。可以试试切换标签页、放宽内存/预算筛选，或点击「全部(含8G/瑕疵)」查看原始列表。</div>`;
      return;
    }

    $("itemList").innerHTML = filtered
      .map((it, idx) => {
        const m = getMark(it);
        const cd = formatCountdown(it.end_ts);
        const genCls =
          it.generation === 14 ? "tag-gen14" :
          it.generation === 13 ? "tag-gen13" :
          it.generation === 12 ? "tag-gen12" : "tag-gen11";
        const scoreCls = it.steal_score >= 70 ? "score-high" : it.steal_score >= 50 ? "score-mid" : "score-low";
        const cardCls =
          it.buy_now_under_budget ? "item-card buy-now-deal" :
          it.under_budget && !it.is_junk ? "item-card hot-deal" : "item-card";

        const sellerTag = it.is_store
          ? `<span class="tag">商家(含10%税)</span>`
          : `<span class="tag tag-green">个人免税卖家</span>`;
        const cpuTag = it.is_p_series
          ? `<span class="tag tag-p">🚀 ${escapeHtml(it.cpu_model)} (P系高性能)</span>`
          : `<span class="tag">${escapeHtml(it.cpu_model)}</span>`;
        const ramTag = it.ram_gb >= 16
          ? `<span class="tag tag-green">内存 ${escapeHtml(it.ram_label)}</span>`
          : `<span class="tag tag-amber">内存 ${escapeHtml(it.ram_label)}</span>`;
        const ssdTag = it.ssd_gb >= 512
          ? `<span class="tag tag-green">SSD ${escapeHtml(it.ssd_label)}</span>`
          : `<span class="tag">SSD ${escapeHtml(it.ssd_label)}</span>`;

        const alertTag =
          it.alert_reason === "buy_now"
            ? `<span class="tag tag-purple">💎 一口价达标可秒</span>`
            : it.alert_reason === "ending_soon"
            ? `<span class="tag tag-green">🔥 快结拍达标捡漏</span>`
            : "";

        const warnHtml = (it.warnings || [])
          .map((w) => `<span class="tag ${w.includes("起拍") ? "tag-amber" : "tag-red"}">⚠️ ${escapeHtml(w)}</span>`)
          .join("");
        const junkHtml = it.is_junk ? `<span class="tag tag-red">⛔ 标题故障/Junk</span>` : "";

        // Deep inspection status & findings
        let inspectBadge = "";
        if (it.detail_inspected) {
          if (it.detail_severe_tags && it.detail_severe_tags.length) {
            inspectBadge = it.detail_severe_tags
              .map((t) => `<span class="tag tag-red">⛔ 正文硬伤: ${escapeHtml(t)}</span>`)
              .join("");
          } else if (it.detail_moderate_tags && it.detail_moderate_tags.length) {
            inspectBadge = it.detail_moderate_tags
              .map((t) => `<span class="tag tag-amber">🔍 正文瑕疵: ${escapeHtml(t)}</span>`)
              .join("");
          } else {
            inspectBadge = `<span class="tag tag-green">✅ 正文已排雷·无硬伤</span>`;
          }
          if (it.detail_minor_tags && it.detail_minor_tags.length) {
            inspectBadge += it.detail_minor_tags
              .map((t) => `<span class="tag">ℹ️ ${escapeHtml(t)}</span>`)
              .join("");
          }
          if (it.detail_positives && it.detail_positives.length) {
            inspectBadge += it.detail_positives
              .map((t) => `<span class="tag tag-green">✨ ${escapeHtml(t)}</span>`)
              .join("");
          }
        } else {
          inspectBadge = `<span class="tag">🔎 未深查正文(点击排雷)</span>`;
        }

        const evidenceArr = it.detail_evidence || [];
        const evidenceHtml = evidenceArr.length
          ? `<div class="evidence-box ${it.has_severe_defect ? "severe" : ""}">
              ${evidenceArr
                .slice(0, 3)
                .map(
                  (ev) =>
                    `<div class="evidence-line" title="${escapeHtml(ev.text)}"><span class="evidence-tag ${escapeHtml(ev.level)}">[${escapeHtml(ev.tag)}]</span>${escapeHtml(ev.text)}</div>`
                )
                .join("")}
            </div>`
          : "";

        const inspectBtnHtml = isLocalServer
          ? `<button class="btn btn-sm btn-inspect" data-aid="${escapeHtml(it.auction_id)}" title="抓取雅虎详情页正文检查铰链/屏幕/键盘/电池暗病">${it.detail_inspected ? "🔄 重查正文" : "🔍 深查排雷"}</button>`
          : "";

        const shipLabel = it.is_free_shipping
          ? "日本包邮"
          : `日内运费 ${it.dom_ship_jpy.toLocaleString()}円${it.dom_ship_known ? "" : "(估)"}`;

        const priceDeltaHtml =
          it.price_delta_jpy > 0
            ? `<span style="color:#f87171;">↑涨${it.price_delta_jpy.toLocaleString()}円</span>`
            : it.price_delta_jpy < 0
            ? `<span style="color:#10b981;">↓降${Math.abs(it.price_delta_jpy).toLocaleString()}円</span>`
            : "";

        const buyNowHtml =
          it.buy_now_price_jpy && !it.is_fixed_price
            ? `<div class="buynow-strip"><span>💎 一口价 ${it.buy_now_price_jpy.toLocaleString()}円</span><strong>折合512G ¥${Math.round(it.buy_now_effective_512_cny)}</strong></div>`
            : "";

        const saveCls = it.savings_vs_ref_cny >= 0 ? "save-badge" : "save-badge neg";
        const saveText =
          it.savings_vs_ref_cny >= 0
            ? `比参考价(¥${Math.round(it.ref_cny)})省 ¥${Math.round(it.savings_vs_ref_cny)}`
            : `高出参考价 ¥${Math.abs(Math.round(it.savings_vs_ref_cny))}`;

        return `
        <article class="${cardCls}" data-aid="${escapeHtml(it.auction_id)}">
          <div class="thumb-wrap">
            <img src="${escapeHtml(it.image_url)}" alt="G83" loading="lazy" referrerpolicy="no-referrer" />
            <span class="score-pill ${scoreCls}">${it.steal_score}分</span>
          </div>

          <div class="item-main">
            <div class="item-title-row">
              <span class="rank-num">#${idx + 1}</span>
              <div class="item-title">${escapeHtml(it.title)}</div>
            </div>

            <div class="badge-row">
              ${alertTag}
              ${inspectBadge}
              <span class="tag ${genCls}">${escapeHtml(it.gen_label_short)}</span>
              ${cpuTag}
              ${ramTag}
              ${ssdTag}
              <span class="tag">${escapeHtml(it.condition_label)}</span>
              ${sellerTag}
              ${junkHtml}
              ${warnHtml}
            </div>

            ${evidenceHtml}

            <div class="meta-line">
              <span class="countdown ${cd.cls}" data-endts="${it.end_ts || 0}">${cd.text}</span>
              <span>出价 <strong>${it.bid_count}</strong> 次</span>
              <span>收藏 <strong>${it.watch_count}</strong> 人</span>
              <span>${shipLabel}</span>
              ${it.is_auto_extend === true ? `<span>⏱️有自动延长</span>` : it.is_auto_extend === false ? `<span style="color:#6ee7b7;">⚡无自动延长</span>` : ""}
              ${it.seller_rating ? `<span>卖家好评 ${escapeHtml(it.seller_rating)}</span>` : ""}
              ${priceDeltaHtml}
            </div>
          </div>

          <div class="item-right">
            <div class="price-box">
              <div class="price-main-row">
                <div>
                  <div class="price-label-sm">${it.ssd_adj_cny > 0 ? "折合512G等效到手 (含+¥" + Math.round(it.ssd_adj_cny) + "换盘)" : "预计未税到手 (已含EMS运费)"}</div>
                  <div class="price-cny ${it.under_budget ? "good" : "over"}">¥${Math.round(it.effective_512_cny)}</div>
                </div>
                <div style="text-align:right;">
                  <div class="price-label-sm">${it.is_fixed_price ? "一口价" : "当前出价"}</div>
                  <div style="font-size:15px;font-weight:700;">${it.price_jpy.toLocaleString()} 円</div>
                </div>
              </div>
              <div class="price-sub">
                <span>裸机未税到手 ¥${Math.round(it.untaxed_cny)}</span>
                <span>若被税13%: ¥${Math.round(it.with_customs_cny)}</span>
              </div>
              <div class="price-sub">
                <span class="${saveCls}">${saveText}</span>
                <span>目标 ≤ ¥${Math.round(it.target_cny)}</span>
              </div>
              ${buyNowHtml}
            </div>

            <div class="action-row">
              <a class="btn btn-sm btn-doorzo" href="${escapeHtml(it.doorzo_url)}" target="_blank" rel="noopener">🚀 去任意门</a>
              <a class="btn btn-sm" href="${escapeHtml(it.yahoo_url)}" target="_blank" rel="noopener">🔗 雅虎原页</a>
              <button class="btn btn-sm btn-copy" data-url="${escapeHtml(it.yahoo_url)}" title="复制雅虎链接粘贴到任意门App搜索框">📋 复制链接</button>
              ${inspectBtnHtml}
              <button class="btn btn-icon btn-star ${m.starred ? "active" : ""}" data-act="star" data-aid="${escapeHtml(it.auction_id)}" title="收藏盯盘">⭐</button>
              <button class="btn btn-icon" data-act="ignore" data-aid="${escapeHtml(it.auction_id)}" title="屏蔽不再显示">✕</button>
            </div>
          </div>
        </article>`;
      })
      .join("");
  }

  // Live 1-second countdown ticker
  setInterval(() => {
    document.querySelectorAll(".countdown[data-endts]").forEach((el) => {
      const endTs = Number(el.getAttribute("data-endts") || 0);
      if (!endTs) return;
      const cd = formatCountdown(endTs);
      el.textContent = cd.text;
      el.className = `countdown ${cd.cls}`;
    });
  }, 1000);

  async function loadData() {
    try {
      const res = await fetch("/api/snapshot", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        isLocalServer = true;
        serverMeta = data.meta || {};
        snapshot = data.snapshot;
        $("modeBadge").textContent = "🟢 本地实时服务模式";
        $("modeBadge").classList.add("live");
        $("btnScan").disabled = !!serverMeta.scanning;
        $("btnScan").textContent = serverMeta.scanning ? "⏳ 扫描中..." : "🔄 立即扫描";
        render();
        return;
      }
    } catch (_) {}

    // Fallback: Static GitHub Pages mode
    try {
      const res = await fetch("./data.json?t=" + Date.now(), { cache: "no-store" });
      if (res.ok) {
        isLocalServer = false;
        snapshot = await res.json();
        $("modeBadge").textContent = "☁️ 云端静态榜单 (GitHub Actions 自动更新)";
        $("btnScan").style.display = "none";
        $("btnSettings").style.display = "none";
        render();
        return;
      }
    } catch (_) {}

    $("itemList").innerHTML = `<div class="empty-state">无法加载数据，请确认已启动本地服务或已生成 data.json。</div>`;
  }

  async function triggerManualScan() {
    if (!isLocalServer) return;
    $("btnScan").disabled = true;
    $("btnScan").textContent = "⏳ 扫描雅虎中...";
    showToast("正在抓取雅虎日拍最新 G83 列表，约需 5~10 秒...");
    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ send_alerts: true }),
      });
      const data = await res.json();
      if (data.snapshot) {
        snapshot = data.snapshot;
        showToast(`✅ 扫描完成！抓到 ${snapshot.summary.total_clean} 台有效机器，${snapshot.summary.under_budget_count} 台达标！`);
      } else {
        showToast("⚠️ 扫描异常：" + (data.error || data.status));
      }
    } catch (e) {
      showToast("扫描请求失败: " + e.message);
    } finally {
      await loadData();
    }
  }

  async function openSettings() {
    if (!isLocalServer) return;
    try {
      const res = await fetch("/api/config");
      fullConfig = await res.json();
      const gr = fullConfig.generation_rules || {};
      const cm = fullConfig.cost_model || {};
      const flt = fullConfig.filters || {};
      const nf = fullConfig.notifications || {};

      $("cfgGen13Max").value = gr["13"]?.max_effective_512_cny ?? 2000;
      $("cfgGen13Ref").value = gr["13"]?.xianyu_ref_cny ?? 2400;
      $("cfgGen12Max").value = gr["12"]?.max_effective_512_cny ?? 1450;
      $("cfgGen12Ref").value = gr["12"]?.xianyu_ref_cny ?? 1850;
      $("cfgGen11Max").value = gr["11"]?.max_effective_512_cny ?? 1000;
      $("cfgGen11Ref").value = gr["11"]?.xianyu_ref_cny ?? 1350;

      $("cfgSpread").value = cm.fx_spread_pct ?? 3.5;
      $("cfgDoorzoFee").value = cm.doorzo_fee_jpy ?? 300;
      $("cfgIntlShip").value = cm.intl_shipping_jpy ?? 4500;
      $("cfgDomShip").value = cm.default_domestic_shipping_jpy ?? 1200;
      $("cfgSsdDiff").value = cm.ssd_upgrade_256_to_512_cny ?? 180;
      $("cfgPollMin").value = fullConfig.poll_interval_minutes ?? 10;
      $("cfgAlertWin").value = flt.alert_ending_within_minutes ?? 180;
      $("cfgMinScore").value = flt.alert_min_steal_score ?? 55;

      $("cfgPushPlus").value = nf.pushplus_token || "";
      $("cfgServerChan").value = nf.serverchan_key || "";
      $("cfgBark").value = nf.bark_url || "";
      $("cfgFeishu").value = nf.feishu_webhook || "";
      $("cfgDingtalk").value = nf.dingtalk_webhook || "";
      $("cfgNtfy").value = nf.ntfy_topic || "";
      $("cfgWinToast").checked = !!nf.windows_toast;

      $("cfgQueries").value = (fullConfig.queries || []).join("\n");
      $("settingsModal").classList.add("open");
    } catch (e) {
      showToast("加载配置失败: " + e.message);
    }
  }

  function readModalConfig() {
    const cfg = JSON.parse(JSON.stringify(fullConfig || {}));
    cfg.queries = $("cfgQueries").value.split("\n").map((s) => s.trim()).filter(Boolean);
    cfg.poll_interval_minutes = Math.max(2, Number($("cfgPollMin").value) || 10);
    cfg.cost_model = {
      ...(cfg.cost_model || {}),
      fx_spread_pct: Number($("cfgSpread").value) || 3.5,
      doorzo_fee_jpy: Number($("cfgDoorzoFee").value) || 300,
      intl_shipping_jpy: Number($("cfgIntlShip").value) || 4500,
      default_domestic_shipping_jpy: Number($("cfgDomShip").value) || 1200,
      ssd_upgrade_256_to_512_cny: Number($("cfgSsdDiff").value) || 180,
    };
    cfg.generation_rules = cfg.generation_rules || {};
    cfg.generation_rules["13"] = { ...(cfg.generation_rules["13"] || {}), max_effective_512_cny: Number($("cfgGen13Max").value) || 2000, xianyu_ref_cny: Number($("cfgGen13Ref").value) || 2400 };
    cfg.generation_rules["12"] = { ...(cfg.generation_rules["12"] || {}), max_effective_512_cny: Number($("cfgGen12Max").value) || 1450, xianyu_ref_cny: Number($("cfgGen12Ref").value) || 1850 };
    cfg.generation_rules["11"] = { ...(cfg.generation_rules["11"] || {}), max_effective_512_cny: Number($("cfgGen11Max").value) || 1000, xianyu_ref_cny: Number($("cfgGen11Ref").value) || 1350 };
    cfg.filters = {
      ...(cfg.filters || {}),
      alert_ending_within_minutes: Number($("cfgAlertWin").value) || 180,
      alert_min_steal_score: Number($("cfgMinScore").value) || 55,
    };
    cfg.notifications = {
      ...(cfg.notifications || {}),
      windows_toast: $("cfgWinToast").checked,
      pushplus_token: $("cfgPushPlus").value.trim(),
      serverchan_key: $("cfgServerChan").value.trim(),
      bark_url: $("cfgBark").value.trim(),
      feishu_webhook: $("cfgFeishu").value.trim(),
      dingtalk_webhook: $("cfgDingtalk").value.trim(),
      ntfy_topic: $("cfgNtfy").value.trim(),
    };
    return cfg;
  }

  // Event wiring
  $("presetTabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    activeTab = btn.dataset.tab;
    render();
  });

  ["filterSearch", "filterGen", "filterRam", "filterSsd", "filterSeller", "sortBy", "chkUnderBudget", "chkHideDefect", "chkOnlyInspected"].forEach((id) => {
    $(id).addEventListener("input", render);
    $(id).addEventListener("change", render);
  });

  $("itemList").addEventListener("click", async (e) => {
    const inspectBtn = e.target.closest(".btn-inspect");
    if (inspectBtn) {
      const aid = inspectBtn.dataset.aid;
      inspectBtn.disabled = true;
      inspectBtn.textContent = "⏳ 排雷中...";
      try {
        const res = await fetch("/api/inspect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ auction_id: aid }),
        });
        const data = await res.json();
        if (data.ok && data.item) {
          const idx = (snapshot?.items || []).findIndex((x) => x.auction_id === aid);
          if (idx >= 0) snapshot.items[idx] = data.item;
          const rep = data.report || {};
          if (rep.severe_tags && rep.severe_tags.length) {
            showToast(`⛔ 排雷拦截！正文检出硬伤: ${rep.severe_tags.join(" / ")}`, 4200);
          } else if (rep.moderate_tags && rep.moderate_tags.length) {
            showToast(`⚠️ 正文检出瑕疵: ${rep.moderate_tags.join(" / ")}`, 3600);
          } else {
            showToast("✅ 正文深查通过：未见铰链/屏幕/键盘等明显硬伤！", 3200);
          }
          render();
        } else {
          showToast("深查失败: " + (data.error || "未知错误"));
          inspectBtn.disabled = false;
          inspectBtn.textContent = "🔍 深查排雷";
        }
      } catch (err) {
        showToast("深查请求失败: " + err.message);
        inspectBtn.disabled = false;
        inspectBtn.textContent = "🔍 深查排雷";
      }
      return;
    }

    const copyBtn = e.target.closest(".btn-copy");
    if (copyBtn) {
      const url = copyBtn.dataset.url;
      try {
        await navigator.clipboard.writeText(url);
        showToast("📋 已复制雅虎链接！打开日淘任意门 App 粘贴到搜索框即可直达");
      } catch (_) {
        prompt("请手动复制雅虎原链接粘贴到任意门：", url);
      }
      return;
    }
    const actBtn = e.target.closest("[data-act]");
    if (actBtn) {
      const act = actBtn.dataset.act;
      const aid = actBtn.dataset.aid;
      await toggleMark(aid, act === "star" ? "starred" : "ignored");
    }
  });

  $("btnScan").addEventListener("click", triggerManualScan);
  $("btnSettings").addEventListener("click", openSettings);
  $("btnCloseModal").addEventListener("click", () => $("settingsModal").classList.remove("open"));
  $("btnCancelModal").addEventListener("click", () => $("settingsModal").classList.remove("open"));

  $("btnSaveConfig").addEventListener("click", async () => {
    const cfg = readModalConfig();
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      });
      const data = await res.json();
      if (data.ok) {
        $("settingsModal").classList.remove("open");
        showToast("✅ 配置已保存！后台正在按新参数重新计算...");
        setTimeout(loadData, 2500);
        setTimeout(loadData, 7000);
      } else {
        showToast("保存失败: " + data.error);
      }
    } catch (e) {
      showToast("保存失败: " + e.message);
    }
  });

  $("btnTestNotify").addEventListener("click", async () => {
    const cfg = readModalConfig();
    showToast("正在发送测试推送...");
    try {
      const res = await fetch("/api/test-notify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notifications: cfg.notifications }),
      });
      const data = await res.json();
      const chs = Object.entries(data.results || {});
      if (!chs.length) {
        showToast("⚠️ 请先勾选桌面通知，或填写至少一个手机推送 Token/Webhook", 3800);
        return;
      }
      const summary = chs.map(([k, v]) => `${k}: ${v.ok ? "成功" : "失败"}`).join(" | ");
      showToast("推送结果 -> " + summary, 4500);
    } catch (e) {
      showToast("测试推送失败: " + e.message);
    }
  });

  // Auto refresh UI every 45s in local mode
  loadData();
  setInterval(() => {
    if (isLocalServer) loadData();
  }, 45000);
})();
