(() => {
  let isLocalServer = false;
  let snapshot = null;
  let serverMeta = {};
  let fullConfig = null;
  let activeProfileId = "all";
  let activeTab = "steals";
  let localMarks = JSON.parse(localStorage.getItem("g83_marks_v1") || "{}");

  // Profile editor state
  let draftProfiles = [];
  let selectedDraftIdx = 0;

  const $ = (id) => document.getElementById(id);

  const FALLBACK_TEMPLATES = [
    { id: "laptop", name: "笔记本电脑", icon: "💻", yahoo_category_id: "23412", intl_shipping_jpy: 4500, default_domestic_shipping_jpy: 1200, customs_tax_rate: 0.13, tax_included_shipping: false, shipping_hint: "内置锂电池，一般走 EMS+加固 (约4500円)，13% 行邮税", defect_summary: "铰链损坏、碎屏/白斑、键盘连击、BIOS锁、电池鼓包" },
    { id: "camera", name: "相机 / 镜头", icon: "📷", yahoo_category_id: "", intl_shipping_jpy: 2800, default_domestic_shipping_jpy: 1000, customs_tax_rate: 0.13, tax_included_shipping: false, shipping_hint: "EMS/航空件 (约2800円)，13% 税", defect_summary: "镜片发霉(カビ)、起雾(クモリ)、脱胶、AF/快门故障" },
    { id: "phone_tablet", name: "手机 / 平板", icon: "📱", yahoo_category_id: "", intl_shipping_jpy: 2500, default_domestic_shipping_jpy: 800, customs_tax_rate: 0.13, tax_included_shipping: false, shipping_hint: "带锂电池走 EMS/航空 (约2500円)，13% 税", defect_summary: "赤ロム网络锁、ID锁、碎屏/烧屏、FaceID故障" },
    { id: "console", name: "游戏机 / 掌机", icon: "🎮", yahoo_category_id: "", intl_shipping_jpy: 2800, default_domestic_shipping_jpy: 1000, customs_tax_rate: 0.13, tax_included_shipping: false, shipping_hint: "EMS/航空件 (约2800円)", defect_summary: "摇杆漂移(ドリフト)、BAN机、读卡故障、按键失灵" },
    { id: "audio", name: "耳机 / 音频 / 数码小件", icon: "🎧", yahoo_category_id: "", intl_shipping_jpy: 1600, default_domestic_shipping_jpy: 800, customs_tax_rate: 0.13, tax_included_shipping: false, shipping_hint: "小航空/EMS (约1600円)", defect_summary: "单耳无声、破音杂音、蓝牙断连、电池衰减" },
    { id: "mouse", name: "鼠标 / 键鼠外设", icon: "🖱️", yahoo_category_id: "", intl_shipping_jpy: 1400, default_domestic_shipping_jpy: 800, customs_tax_rate: 0.13, tax_included_shipping: false, shipping_hint: "无线鼠标约350g，航空小包/EMS约1400円", defect_summary: "微动双击(チャタリング)、滚轮回滚、缺接收器" },
    { id: "figure", name: "手办 / 模型 / 潮玩", icon: "🧸", yahoo_category_id: "", intl_shipping_jpy: 1200, default_domestic_shipping_jpy: 900, customs_tax_rate: 0.0, tax_included_shipping: true, shipping_hint: "可走任意门竹蜻蜓包税小包 (约1200円，0关税)", defect_summary: "缺件、断件粘修、疑似散货、出油发粘、无盒" },
    { id: "fashion", name: "鞋服 / 包包 / 手表", icon: "👟", yahoo_category_id: "", intl_shipping_jpy: 1800, default_domestic_shipping_jpy: 900, customs_tax_rate: 0.0, tax_included_shipping: true, shipping_hint: "非带电多可走竹蜻蜓包税线 (约1800円)", defect_summary: "开胶粉化、破洞污渍、发霉脱皮、手表停走" },
    { id: "general", name: "通用二手好物", icon: "📦", yahoo_category_id: "", intl_shipping_jpy: 2000, default_domestic_shipping_jpy: 1000, customs_tax_rate: 0.13, tax_included_shipping: false, shipping_hint: "可自定义运费与是否包税", defect_summary: "故障(ジャンク)、破损开裂、未测动作、明显瑕疵" },
  ];

  function getTemplates() {
    return (snapshot?.templates && snapshot.templates.length) ? snapshot.templates : FALLBACK_TEMPLATES;
  }

  function findTemplate(catId) {
    return getTemplates().find((t) => t.id === catId) || getTemplates()[getTemplates().length - 1];
  }

  function getGitHubRepoInfo() {
    const m = window.location.hostname.match(/^([^.]+)\.github\.io$/i);
    const repo = window.location.pathname.split("/").filter(Boolean)[0];
    if (m && repo) return { owner: m[1], repo };
    return { owner: "bianfu69-cell", repo: "111" };
  }

  function showToast(msg, duration = 2800) {
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
    if (isLocalServer) return { starred: !!it.starred, ignored: !!it.ignored };
    const m = localMarks[it.auction_id] || {};
    return { starred: !!m.starred, ignored: !!m.ignored };
  }

  async function toggleMark(auctionId, field) {
    const targets = (snapshot?.items || []).filter((x) => x.auction_id === auctionId);
    if (!targets.length) return;
    const cur = getMark(targets[0]);
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
          targets.forEach((it) => {
            it.starred = data.mark.starred;
            it.ignored = data.mark.ignored;
          });
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

  function getActiveProfileObj() {
    if (activeProfileId === "all") return null;
    return (snapshot?.profiles || []).find((p) => p.id === activeProfileId) || null;
  }

  function getProfileScopedItems(items) {
    if (activeProfileId === "all") return items;
    return items.filter((it) => (it.profile_id || "dynabook_g83") === activeProfileId);
  }

  function getTabFilteredBase(items, tab) {
    const nowSec = Math.floor(Date.now() / 1000);
    const scoped = getProfileScopedItems(items);
    const alive = scoped.filter((it) => {
      const m = getMark(it);
      if (m.ignored) return false;
      if (it.end_ts && it.end_ts < nowSec - 60) return false;
      return true;
    });

    if (tab === "all") return alive;
    if (tab === "starred") return alive.filter((it) => getMark(it).starred);

    const clean = alive.filter((it) => {
      if (it.is_junk || it.has_severe_defect) return false;
      if ((it.category || "laptop") === "laptop" && it.cpu_tier === "i3") return false;
      return true;
    });

    if (tab === "steals") {
      return clean.filter((it) => {
        if ((it.profile_id || "dynabook_g83") === "dynabook_g83") {
          return [14, 13, 12, 11].includes(it.generation);
        }
        return true;
      });
    }
    if (tab === "under") return clean.filter((it) => it.under_budget || it.buy_now_under_budget);
    if (tab === "ending") {
      return clean.filter((it) => {
        const rem = it.end_ts ? it.end_ts - nowSec : it.remaining_sec;
        return rem > 0 && rem <= 10800;
      });
    }
    if (tab === "buynow") return clean.filter((it) => it.buy_now_price_jpy && it.buy_now_effective_512_cny);
    return clean;
  }

  function renderProfileStrip() {
    const sums = snapshot?.profile_summaries || [];
    const totalClean = snapshot?.summary?.total_clean ?? 0;
    const totalUnder = snapshot?.summary?.under_budget_count ?? 0;

    let html = `
      <button class="profile-pill ${activeProfileId === "all" ? "active" : ""}" data-pid="all">
        🌐 全部商品总榜 <span class="pill-stat">${totalClean}</span>
        ${totalUnder > 0 ? `<span class="pill-deal">${totalUnder}达标</span>` : ""}
      </button>`;

    sums.forEach((ps) => {
      if (!ps.enabled) return;
      html += `
        <button class="profile-pill ${activeProfileId === ps.id ? "active" : ""}" data-pid="${escapeHtml(ps.id)}">
          ${escapeHtml(ps.icon || "📦")} ${escapeHtml(ps.name)}
          <span class="pill-stat">${ps.clean_count}</span>
          ${ps.under_budget_count > 0 ? `<span class="pill-deal">${ps.under_budget_count}达标</span>` : ""}
        </button>`;
    });

    html += `<button class="profile-pill profile-pill-add" data-pid="__add__">＋ 添加新商品</button>`;
    $("profileBar").innerHTML = html;
  }

  function render() {
    if (!snapshot || !Array.isArray(snapshot.items)) {
      $("itemList").innerHTML = `<div class="empty-state">暂无扫描数据，点击右上角「立即扫描」开始抓取雅虎日拍！</div>`;
      return;
    }

    renderProfileStrip();

    const items = snapshot.items;
    const activeProf = getActiveProfileObj();
    const isLaptopView = activeProf ? activeProf.category === "laptop" : (snapshot.profiles || []).every((p) => !p.enabled || p.category === "laptop");
    document.querySelectorAll(".laptop-only-ctl").forEach((el) => {
      el.style.display = isLaptopView ? "" : "none";
    });

    // Scoped KPIs
    const scopedAlive = getProfileScopedItems(items).filter((it) => !getMark(it).ignored);
    const scopedClean = scopedAlive.filter((it) => !it.is_junk && !it.has_severe_defect);
    const scopedUnder = scopedClean.filter((it) => it.under_budget || it.buy_now_under_budget);
    const nowSec = Math.floor(Date.now() / 1000);
    const scopedEnding = scopedClean.filter((it) => {
      const rem = it.end_ts ? it.end_ts - nowSec : it.remaining_sec;
      return rem > 0 && rem <= 10800;
    });
    const scopedInspected = scopedAlive.filter((it) => it.detail_inspected).length;
    const scopedSevere = scopedAlive.filter((it) => (it.detail_severe_tags || []).length > 0).length;

    $("kpiClean").textContent = scopedClean.length;
    $("kpiRaw").textContent = `正文深查 ${scopedInspected} 件 · 拦截硬伤 ${scopedSevere} 件`;
    $("kpiUnderBudget").textContent = scopedUnder.length;
    $("kpiEndingSoon").textContent = scopedEnding.length;

    if (activeProf) {
      const lowest = scopedClean.length ? Math.round(Math.min(...scopedClean.map((x) => x.effective_512_cny))) : null;
      $("kpi4Label").textContent = `${activeProf.icon || "📦"} ${activeProf.name} 最低到手`;
      $("kpi4Val").textContent = lowest !== null ? `¥${lowest}` : "-";
      $("kpi4Sub").textContent = `目标 ≤ ¥${Math.round(activeProf.target_cny)} · 参考 ¥${Math.round(activeProf.ref_cny)} · 运费 ${activeProf.intl_shipping_jpy}円`;
      $("kpiBudgetDesc").textContent = activeProf.tax_included_shipping ? "已按包税专线(0关税)估算" : `EMS/航空估算 · 税率 ${Math.round((activeProf.customs_tax_rate || 0.13) * 100)}%`;
    } else {
      const enabledCount = (snapshot.profiles || []).filter((p) => p.enabled !== false).length;
      const lowestAll = scopedClean.length ? Math.round(Math.min(...scopedClean.map((x) => x.effective_512_cny))) : null;
      $("kpi4Label").textContent = "监控商品数 / 全场最低";
      $("kpi4Val").textContent = `${enabledCount} 个${lowestAll !== null ? " · ¥" + lowestAll : ""}`;
      $("kpi4Sub").textContent = "点击上方「➕ 添加/管理商品」随时扩展";
      $("kpiBudgetDesc").textContent = "各商品独立预算与专属排雷库";
    }

    $("kpiFx").textContent = snapshot.fx_effective ? snapshot.fx_effective.toFixed(4) : "-";
    const cm = (snapshot.config_public || {}).cost_model || {};
    $("kpiFxSub").textContent = `基准 ${snapshot.fx_base || "-"} + ${cm.fx_spread_pct ?? 3.5}%汇损 · 代拍费 ${cm.doorzo_fee_jpy ?? 300}円`;

    // Status line with live relative freshness
    let nextStr = "";
    const ageMin = snapshot.scanned_ts ? Math.max(0, Math.floor((Date.now() / 1000 - snapshot.scanned_ts) / 60)) : null;
    const ageTxt = ageMin === null ? "" : (ageMin === 0 ? "（刚刚更新）" : `（${ageMin}分钟前）`);
    if (isLocalServer && serverMeta.next_scan_ts) {
      const leftMin = Math.max(0, Math.ceil((serverMeta.next_scan_ts - Date.now() / 1000) / 60));
      nextStr = serverMeta.scanning ? " · 正在后台扫描中..." : ` · 约 ${leftMin} 分钟后自动刷新`;
    } else if (!isLocalServer) {
      nextStr = " · GitHub云端每15分钟自动更新";
    }
    $("statusSub").textContent = `上次扫描: ${snapshot.scanned_at}${ageTxt}${nextStr}`;

    // Tab counts
    const laptopRamGuard = (arr) =>
      isLaptopView && $("filterRam").value === "16plus"
        ? arr.filter((x) => (x.category || "laptop") !== "laptop" || (x.ram_gb && x.ram_gb >= 16))
        : arr;

    $("cntSteals").textContent = laptopRamGuard(getTabFilteredBase(items, "steals")).length;
    $("cntUnder").textContent = laptopRamGuard(getTabFilteredBase(items, "under")).length;
    $("cntEnding").textContent = laptopRamGuard(getTabFilteredBase(items, "ending")).length;
    $("cntBuyNow").textContent = laptopRamGuard(getTabFilteredBase(items, "buynow")).length;
    $("cntStarred").textContent = getTabFilteredBase(items, "starred").length;
    $("cntAll").textContent = getTabFilteredBase(items, "all").length;

    // Apply filters
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
        `${it.title} ${it.profile_name || ""} ${it.cpu_model || ""} ${it.gen_label_short || ""} ${it.auction_id}`.toLowerCase().includes(q)
      );
    }

    if (isLaptopView) {
      if (fGen === "13plus") filtered = filtered.filter((it) => it.generation === 13 || it.generation === 14);
      else if (fGen === "12") filtered = filtered.filter((it) => it.generation === 12);
      else if (fGen === "11") filtered = filtered.filter((it) => it.generation === 11);

      if (activeTab !== "all" && activeTab !== "starred" && fRam === "16plus") {
        filtered = filtered.filter((it) => (it.category || "laptop") !== "laptop" || (it.ram_gb && it.ram_gb >= 16));
      }
      if (fSsd === "512plus") filtered = filtered.filter((it) => it.ssd_gb && it.ssd_gb >= 512);
      else if (fSsd === "256") filtered = filtered.filter((it) => it.ssd_gb === 256);
    }

    if (fSeller === "personal") filtered = filtered.filter((it) => !it.is_store);
    else if (fSeller === "store") filtered = filtered.filter((it) => it.is_store);

    if (onlyBudget) filtered = filtered.filter((it) => it.under_budget || it.buy_now_under_budget);
    if (hideDefect) filtered = filtered.filter((it) => !it.has_defect && !it.has_severe_defect && !it.is_junk);
    if (onlyInspected) filtered = filtered.filter((it) => !!it.detail_inspected);

    const sortBy = $("sortBy").value;
    filtered.sort((a, b) => {
      if (activeTab === "buynow" && sortBy === "score") {
        return (a.buy_now_effective_512_cny ?? 99999) - (b.buy_now_effective_512_cny ?? 99999);
      }
      if (activeTab === "ending" && sortBy === "score") {
        return (a.end_ts || 9e12) - (b.end_ts || 9e12);
      }
      if (sortBy === "eff512") return a.effective_512_cny - b.effective_512_cny;
      if (sortBy === "ending") return (a.end_ts || 9e12) - (b.end_ts || 9e12);
      if (sortBy === "savings") return b.savings_vs_ref_cny - a.savings_vs_ref_cny;
      return b.steal_score - a.steal_score || a.effective_512_cny - b.effective_512_cny;
    });

    $("resultCount").textContent = `当前筛选共 ${filtered.length} 件商品`;

    if (!filtered.length) {
      $("itemList").innerHTML = `<div class="empty-state">当前筛选条件下暂无符合商品。可以切换标签页、放宽筛选，或点击「全部(含硬伤/瑕疵)」查看原始列表。</div>`;
      return;
    }

    $("itemList").innerHTML = filtered
      .map((it, idx) => {
        const m = getMark(it);
        const cd = formatCountdown(it.end_ts);
        const isLap = (it.category || "laptop") === "laptop";
        const scoreCls = it.steal_score >= 70 ? "score-high" : it.steal_score >= 50 ? "score-mid" : "score-low";
        const cardCls =
          it.buy_now_under_budget ? "item-card buy-now-deal" :
          it.under_budget && !it.is_junk && !it.has_severe_defect ? "item-card hot-deal" : "item-card";

        const sellerTag = it.is_store ? `<span class="tag">商家(含10%税)</span>` : `<span class="tag tag-green">个人免税卖家</span>`;
        const profBadge = activeProfileId === "all"
          ? `<span class="tag tag-gen13">${escapeHtml((it.profile_icon || "📦") + " " + (it.profile_name || "商品"))}</span>`
          : "";

        let specTagsHtml = "";
        if (isLap) {
          const genCls =
            it.generation === 14 ? "tag-gen14" :
            it.generation === 13 ? "tag-gen13" :
            it.generation === 12 ? "tag-gen12" : "tag-gen11";
          const cpuTag = it.is_p_series
            ? `<span class="tag tag-p">🚀 ${escapeHtml(it.cpu_model)}</span>`
            : (it.cpu_model ? `<span class="tag">${escapeHtml(it.cpu_model)}</span>` : "");
          const ramTag = it.ram_label ? `<span class="tag ${it.ram_gb >= 16 ? "tag-green" : "tag-amber"}">${escapeHtml(it.ram_label)}</span>` : "";
          const ssdTag = it.ssd_label ? `<span class="tag ${it.ssd_gb >= 512 ? "tag-green" : ""}">${escapeHtml(it.ssd_label)}</span>` : "";
          specTagsHtml = `<span class="tag ${genCls}">${escapeHtml(it.gen_label_short)}</span>${cpuTag}${ramTag}${ssdTag}`;
        } else {
          specTagsHtml = `<span class="tag tag-gen12">${escapeHtml(it.category_name || "二手好物")}</span>` +
            (it.cpu_model ? `<span class="tag tag-green">${escapeHtml(it.cpu_model)}</span>` : "");
        }

        const alertTag =
          it.alert_reason === "buy_now" ? `<span class="tag tag-purple">💎 一口价达标可秒</span>` :
          it.alert_reason === "ending_soon" ? `<span class="tag tag-green">🔥 快结拍达标捡漏</span>` : "";

        const warnHtml = (it.warnings || [])
          .map((w) => `<span class="tag ${w.includes("起拍") ? "tag-amber" : "tag-red"}">⚠️ ${escapeHtml(w)}</span>`)
          .join("");
        const junkHtml = it.is_junk ? `<span class="tag tag-red">⛔ 标题故障/Junk</span>` : "";

        let inspectBadge = "";
        if (it.detail_inspected) {
          if (it.detail_severe_tags && it.detail_severe_tags.length) {
            inspectBadge = it.detail_severe_tags.map((t) => `<span class="tag tag-red">⛔ 正文硬伤: ${escapeHtml(t)}</span>`).join("");
          } else if (it.detail_moderate_tags && it.detail_moderate_tags.length) {
            inspectBadge = it.detail_moderate_tags.map((t) => `<span class="tag tag-amber">🔍 正文瑕疵: ${escapeHtml(t)}</span>`).join("");
          } else {
            inspectBadge = `<span class="tag tag-green">✅ 正文已排雷·无硬伤</span>`;
          }
          if (it.detail_minor_tags && it.detail_minor_tags.length) {
            inspectBadge += it.detail_minor_tags.map((t) => `<span class="tag">ℹ️ ${escapeHtml(t)}</span>`).join("");
          }
          if (it.detail_positives && it.detail_positives.length) {
            inspectBadge += it.detail_positives.map((t) => `<span class="tag tag-green">✨ ${escapeHtml(t)}</span>`).join("");
          }
        } else {
          inspectBadge = `<span class="tag">🔎 未深查正文</span>`;
        }

        const evidenceArr = it.detail_evidence || [];
        const evidenceHtml = evidenceArr.length
          ? `<div class="evidence-box ${it.has_severe_defect ? "severe" : ""}">
              ${evidenceArr.slice(0, 3).map((ev) =>
                `<div class="evidence-line" title="${escapeHtml(ev.text)}"><span class="evidence-tag ${escapeHtml(ev.level)}">[${escapeHtml(ev.tag)}]</span>${escapeHtml(ev.text)}</div>`
              ).join("")}
            </div>`
          : "";

        const shipLabel = it.is_free_shipping ? "日本包邮" : `日内运费 ${it.dom_ship_jpy.toLocaleString()}円${it.dom_ship_known ? "" : "(估)"}`;
        const priceDeltaHtml =
          it.price_delta_jpy > 0 ? `<span style="color:#f87171;">↑涨${it.price_delta_jpy.toLocaleString()}円</span>` :
          it.price_delta_jpy < 0 ? `<span style="color:#10b981;">↓降${Math.abs(it.price_delta_jpy).toLocaleString()}円</span>` : "";

        const buyNowHtml =
          it.buy_now_price_jpy && !it.is_fixed_price
            ? `<div class="buynow-strip"><span>💎 一口价 ${it.buy_now_price_jpy.toLocaleString()}円</span><strong>到手 ¥${Math.round(it.buy_now_effective_512_cny)}</strong></div>`
            : "";

        const saveCls = it.savings_vs_ref_cny >= 0 ? "save-badge" : "save-badge neg";
        const saveText =
          it.savings_vs_ref_cny >= 0
            ? `比参考价(¥${Math.round(it.ref_cny)})省 ¥${Math.round(it.savings_vs_ref_cny)}`
            : `高出参考价 ¥${Math.abs(Math.round(it.savings_vs_ref_cny))}`;

        const costCaption = it.ssd_adj_cny > 0
          ? `折合512G等效到手 (含+¥${Math.round(it.ssd_adj_cny)}换盘)`
          : (it.tax_included_shipping ? `预计包税到手 (含${it.intl_shipping_jpy || 1200}円国际运费)` : `预计未税到手 (含${it.intl_shipping_jpy || 2000}円国际运费)`);

        const taxLine = it.tax_included_shipping
          ? `<span>📦 竹蜻蜓等包税专线估算</span><span>无额外关税</span>`
          : `<span>裸机未税 ¥${Math.round(it.untaxed_cny)}</span><span>若被税: ¥${Math.round(it.with_customs_cny)}</span>`;

        const inspectBtnHtml = isLocalServer
          ? `<button class="btn btn-sm btn-inspect" data-aid="${escapeHtml(it.auction_id)}" data-cat="${escapeHtml(it.category || "general")}" data-pid="${escapeHtml(it.profile_id || "")}">${it.detail_inspected ? "🔄 重查正文" : "🔍 深查排雷"}</button>`
          : "";

        return `
        <article class="${cardCls}" data-aid="${escapeHtml(it.auction_id)}">
          <div class="thumb-wrap">
            <img src="${escapeHtml(it.image_url)}" alt="item" loading="lazy" referrerpolicy="no-referrer" />
            <span class="score-pill ${scoreCls}">${it.steal_score}分</span>
          </div>

          <div class="item-main">
            <div class="item-title-row">
              <span class="rank-num">#${idx + 1}</span>
              <div class="item-title">${escapeHtml(it.title)}</div>
            </div>

            <div class="badge-row">
              ${alertTag}
              ${profBadge}
              ${inspectBadge}
              ${specTagsHtml}
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
              ${it.seller_rating ? `<span>好评 ${escapeHtml(it.seller_rating)}</span>` : ""}
              ${priceDeltaHtml}
            </div>
          </div>

          <div class="item-right">
            <div class="price-box">
              <div class="price-main-row">
                <div>
                  <div class="price-label-sm">${costCaption}</div>
                  <div class="price-cny ${it.under_budget ? "good" : "over"}">¥${Math.round(it.effective_512_cny)}</div>
                </div>
                <div style="text-align:right;">
                  <div class="price-label-sm">${it.is_fixed_price ? "一口价" : "当前出价"}</div>
                  <div style="font-size:15px;font-weight:700;">${it.price_jpy.toLocaleString()} 円</div>
                </div>
              </div>
              <div class="price-sub">${taxLine}</div>
              <div class="price-sub">
                <span class="${saveCls}">${saveText}</span>
                <span>目标 ≤ ¥${Math.round(it.target_cny)}</span>
              </div>
              ${buyNowHtml}
            </div>

            <div class="action-row">
              <a class="btn btn-sm btn-doorzo" href="${escapeHtml(it.doorzo_url)}" target="_blank" rel="noopener">🚀 去任意门</a>
              <a class="btn btn-sm" href="${escapeHtml(it.yahoo_url)}" target="_blank" rel="noopener">🔗 雅虎原页</a>
              <button class="btn btn-sm btn-copy" data-url="${escapeHtml(it.yahoo_url)}">📋 复制链接</button>
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

  async function loadData(showFeedback = false) {
    const isLikelyLocal = ["127.0.0.1", "localhost"].includes(window.location.hostname) || window.location.port === "8783";
    if (isLikelyLocal) {
      try {
        const res = await fetch("/api/snapshot", { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          isLocalServer = true;
          serverMeta = data.meta || {};
          snapshot = data.snapshot;
          $("modeBadge").textContent = "🟢 本地实时服务模式";
          $("modeBadge").classList.add("live");
          $("btnScan").style.display = "";
          $("btnScan").disabled = !!serverMeta.scanning;
          $("btnScan").textContent = serverMeta.scanning ? "⏳ 扫描中..." : "🔄 立即扫描";
          $("btnSyncGh").style.display = "";
          $("btnSettings").style.display = "";
          render();
          return;
        }
      } catch (_) {}
    }

    const { owner, repo } = getGitHubRepoInfo();
    const urls = [
      "./data.json?t=" + Date.now(),
      `https://raw.githubusercontent.com/${owner}/${repo}/main/docs/data.json?t=${Date.now()}`,
    ];

    let bestSnap = null;
    for (const u of urls) {
      try {
        const res = await fetch(u, { cache: "no-store" });
        if (res.ok) {
          const cand = await res.json();
          if (!bestSnap || (cand.scanned_ts || 0) > (bestSnap.scanned_ts || 0)) bestSnap = cand;
        }
      } catch (_) {}
    }

    if (bestSnap) {
      const prevTs = snapshot?.scanned_ts || 0;
      isLocalServer = false;
      snapshot = bestSnap;
      $("modeBadge").textContent = "☁️ 云端自动盯盘 (约15分钟更新)";
      $("modeBadge").classList.add("live");
      $("btnScan").style.display = "";
      $("btnScan").disabled = false;
      $("btnScan").textContent = "🔄 拉取最新云端数据";
      $("btnSyncGh").style.display = "none";
      $("btnSettings").style.display = "none";
      render();
      if (showFeedback) {
        if (snapshot.scanned_ts && snapshot.scanned_ts > prevTs && prevTs > 0) {
          showToast(`✅ 已更新到最新云端快照 (${snapshot.scanned_at})`);
        } else {
          showToast(`当前最新云端快照为 ${snapshot.scanned_at}`);
        }
      }
      return;
    }

    $("itemList").innerHTML = `<div class="empty-state">无法加载数据，请确认已启动本地服务或已生成 data.json。</div>`;
  }

  async function triggerManualScan() {
    if (!isLocalServer) {
      $("btnScan").disabled = true;
      $("btnScan").textContent = "⏳ 拉取中...";
      await loadData(true);
      return;
    }
    $("btnScan").disabled = true;
    $("btnScan").textContent = "⏳ 扫描雅虎中...";
    showToast("正在扫描所有监控商品并执行正文排雷，约需 15~35 秒...");
    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ send_alerts: true }),
      });
      const data = await res.json();
      if (data.snapshot) {
        snapshot = data.snapshot;
        showToast(`✅ 扫描完成！有效 ${snapshot.summary.total_clean} 件，达标 ${snapshot.summary.under_budget_count} 件！`);
      } else {
        showToast("⚠️ 扫描异常：" + (data.error || data.status));
      }
    } catch (e) {
      showToast("扫描请求失败: " + e.message);
    } finally {
      await loadData();
    }
  }

  // ==================== SELF-SERVICE PROFILE MANAGER ====================
  function populateTemplateSelect() {
    $("pmCategory").innerHTML = getTemplates()
      .map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.icon + " " + t.name)}</option>`)
      .join("");
  }

  function updateTemplateHint(catId) {
    const tpl = findTemplate(catId);
    $("pmTplHint").innerHTML =
      `<strong>${escapeHtml(tpl.icon + " " + tpl.name)} 模板说明：</strong>${escapeHtml(tpl.shipping_hint)}<br/>` +
      `<strong>🔍 自动正文排雷范围：</strong>${escapeHtml(tpl.defect_summary)}`;
    $("pmLaptopBox").style.display = catId === "laptop" ? "" : "none";
  }

  function renderPmSidebar() {
    $("pmList").innerHTML = draftProfiles
      .map((p, idx) => {
        const tpl = findTemplate(p.category || "general");
        return `
          <div class="pm-item ${idx === selectedDraftIdx ? "active" : ""} ${p.enabled === false ? "disabled" : ""}" data-pidx="${idx}">
            <div>
              <div class="pm-item-title">${escapeHtml((p.icon || tpl.icon) + " " + p.name)}</div>
              <div class="pm-item-sub">${escapeHtml(tpl.name)} · ≤¥${Math.round(p.target_cny || 0)} ${p.enabled === false ? "(已暂停)" : ""}</div>
            </div>
          </div>`;
      })
      .join("");
  }

  function loadDraftIntoForm(idx) {
    if (idx < 0 || idx >= draftProfiles.length) return;
    selectedDraftIdx = idx;
    const p = draftProfiles[idx];
    const tpl = findTemplate(p.category || "general");

    $("pmFormTitle").textContent = `编辑：${p.icon || tpl.icon} ${p.name}`;
    $("pmName").value = p.name || "";
    $("pmCategory").value = tpl.id;
    $("pmTargetCny").value = p.target_cny ?? 1000;
    $("pmRefCny").value = p.ref_cny ?? 1300;
    $("pmQueries").value = (p.queries || []).join("\n");
    $("pmIntlShip").value = p.intl_shipping_jpy ?? tpl.intl_shipping_jpy;
    $("pmDomShip").value = p.default_domestic_shipping_jpy ?? tpl.default_domestic_shipping_jpy;
    $("pmMustInclude").value = (p.must_include || []).join(", ");
    $("pmExclude").value = (p.exclude_keywords || []).join(", ");
    $("pmEnabled").checked = p.enabled !== false;
    $("pmTaxIncl").checked = !!p.tax_included_shipping;
    $("pmAlertEnabled").checked = p.alert_enabled !== false;
    $("pmBuyNowAlert").checked = p.alert_buy_now_immediately !== false;

    updateTemplateHint(tpl.id);
    if (tpl.id === "laptop") {
      const lo = p.laptop_options || {};
      $("pmSsdDiff").value = lo.ssd_upgrade_256_to_512_cny ?? 0;
      $("pmAucCat").value = p.yahoo_category_id ?? "23412";
      $("pmReq16").checked = !!lo.require_16gb;
      $("pmExclI3").checked = !!lo.exclude_i3;
      const gr = lo.generation_rules || {};
      const hasGen = Object.keys(gr).length > 0 || p.special_preset === "dynabook_g83";
      $("pmG83GenBox").style.display = hasGen ? "" : "none";
      if (hasGen) {
        $("pmG13Max").value = gr["13"]?.max_effective_512_cny ?? 2000;
        $("pmG13Ref").value = gr["13"]?.xianyu_ref_cny ?? 2400;
        $("pmG12Max").value = gr["12"]?.max_effective_512_cny ?? 1450;
        $("pmG12Ref").value = gr["12"]?.xianyu_ref_cny ?? 1850;
        $("pmG11Max").value = gr["11"]?.max_effective_512_cny ?? 1000;
        $("pmG11Ref").value = gr["11"]?.xianyu_ref_cny ?? 1350;
      }
    }
    renderPmSidebar();
  }

  function saveFormBackToDraft() {
    if (selectedDraftIdx < 0 || selectedDraftIdx >= draftProfiles.length) return;
    const p = draftProfiles[selectedDraftIdx];
    const catId = $("pmCategory").value || "general";
    const tpl = findTemplate(catId);
    const splitCsv = (s) => s.split(/[,，\n]+/).map((x) => x.trim()).filter(Boolean);

    p.name = $("pmName").value.trim() || "未命名商品";
    p.category = tpl.id;
    p.icon = tpl.icon;
    p.target_cny = Math.max(10, Number($("pmTargetCny").value) || 1000);
    p.ref_cny = Math.max(p.target_cny, Number($("pmRefCny").value) || Math.round(p.target_cny * 1.25));
    p.queries = $("pmQueries").value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!p.queries.length) p.queries = [p.name];
    p.intl_shipping_jpy = Math.max(0, Number($("pmIntlShip").value) || 0);
    p.default_domestic_shipping_jpy = Math.max(0, Number($("pmDomShip").value) || 0);
    p.must_include = splitCsv($("pmMustInclude").value);
    p.exclude_keywords = splitCsv($("pmExclude").value);
    p.enabled = $("pmEnabled").checked;
    p.tax_included_shipping = $("pmTaxIncl").checked;
    p.customs_tax_rate = p.tax_included_shipping ? 0.0 : (tpl.customs_tax_rate || 0.13);
    p.alert_enabled = $("pmAlertEnabled").checked;
    p.alert_buy_now_immediately = $("pmBuyNowAlert").checked;

    if (tpl.id === "laptop") {
      p.yahoo_category_id = $("pmAucCat").value.trim();
      const prevLo = p.laptop_options || {};
      p.laptop_options = {
        ...prevLo,
        require_16gb: $("pmReq16").checked,
        exclude_i3: $("pmExclI3").checked,
        ssd_upgrade_256_to_512_cny: Math.max(0, Number($("pmSsdDiff").value) || 0),
      };
      if ($("pmG83GenBox").style.display !== "none") {
        const gr = prevLo.generation_rules || {};
        p.laptop_options.generation_rules = {
          ...gr,
          "13": { ...(gr["13"] || { enabled: true, label: "13代" }), max_effective_512_cny: Number($("pmG13Max").value) || 2000, xianyu_ref_cny: Number($("pmG13Ref").value) || 2400 },
          "12": { ...(gr["12"] || { enabled: true, label: "12代" }), max_effective_512_cny: Number($("pmG12Max").value) || 1450, xianyu_ref_cny: Number($("pmG12Ref").value) || 1850 },
          "11": { ...(gr["11"] || { enabled: true, label: "11代" }), max_effective_512_cny: Number($("pmG11Max").value) || 1000, xianyu_ref_cny: Number($("pmG11Ref").value) || 1350 },
        };
      }
    } else {
      p.yahoo_category_id = tpl.yahoo_category_id || "";
      delete p.laptop_options;
    }
    renderPmSidebar();
  }

  async function openProfileManager(createNew = false) {
    populateTemplateSelect();
    if (isLocalServer) {
      try {
        const res = await fetch("/api/profiles");
        const data = await res.json();
        draftProfiles = JSON.parse(JSON.stringify(data.profiles || []));
      } catch (_) {
        draftProfiles = JSON.parse(JSON.stringify(snapshot?.profiles || []));
      }
      $("ghMobileBox").style.display = "none";
      $("btnSaveProfilesLocal").style.display = "";
      $("btnSaveProfilesCloud").textContent = "☁️ 保存并同步到 GitHub 云端";
      $("pmFooterHint").textContent = "可先保存到本地测试，或一键同步到 GitHub 24小时云端盯盘";
    } else {
      // Static GitHub Pages mode: load latest profiles.json directly from GitHub raw or snapshot
      const { owner, repo } = getGitHubRepoInfo();
      $("ghRepoLabel").textContent = `${owner}/${repo}`;
      $("ghMobileBox").style.display = "";
      $("ghPatInput").value = localStorage.getItem("radar_gh_pat_v1") || "";
      $("btnSaveProfilesLocal").style.display = "none";
      $("btnSaveProfilesCloud").textContent = "☁️ 保存到 GitHub 并立即云端扫描";
      $("pmFooterHint").textContent = "手机端保存后会自动提交到 GitHub 并触发云端扫描（约30秒出新榜单）";
      try {
        const r = await fetch(`https://raw.githubusercontent.com/${owner}/${repo}/main/profiles.json?t=${Date.now()}`, { cache: "no-store" });
        if (r.ok) {
          const j = await r.json();
          draftProfiles = JSON.parse(JSON.stringify(j.profiles || []));
        } else {
          draftProfiles = JSON.parse(JSON.stringify(snapshot?.profiles || []));
        }
      } catch (_) {
        draftProfiles = JSON.parse(JSON.stringify(snapshot?.profiles || []));
      }
    }

    if (!draftProfiles.length || createNew) {
      addBlankDraftProfile();
    } else {
      loadDraftIntoForm(0);
    }
    $("profilesModal").classList.add("open");
  }

  function addBlankDraftProfile() {
    const tpl = findTemplate("camera");
    draftProfiles.push({
      id: "item_" + Date.now().toString(36),
      name: "",
      icon: tpl.icon,
      category: tpl.id,
      enabled: true,
      queries: [],
      must_include: [],
      exclude_keywords: [],
      yahoo_category_id: tpl.yahoo_category_id,
      target_cny: 1500,
      ref_cny: 2000,
      intl_shipping_jpy: tpl.intl_shipping_jpy,
      default_domestic_shipping_jpy: tpl.default_domestic_shipping_jpy,
      customs_tax_rate: tpl.customs_tax_rate,
      tax_included_shipping: tpl.tax_included_shipping,
      alert_enabled: true,
      alert_ending_within_minutes: 180,
      alert_buy_now_immediately: true,
      alert_min_steal_score: 55,
    });
    loadDraftIntoForm(draftProfiles.length - 1);
    $("pmName").focus();
  }

  async function saveProfilesRemoteFromMobile() {
    const pat = ($("ghPatInput").value.trim() || localStorage.getItem("radar_gh_pat_v1") || "").trim();
    if (!pat) {
      showToast("⚠️ 请先在紫色框里粘贴你的 GitHub Token（只保存在你手机本地）", 4200);
      $("ghPatInput").focus();
      return;
    }
    localStorage.setItem("radar_gh_pat_v1", pat);
    const { owner, repo } = getGitHubRepoInfo();
    const apiBase = `https://api.github.com/repos/${owner}/${repo}`;
    const headers = {
      Authorization: `Bearer ${pat}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
    };

    $("btnSaveProfilesCloud").disabled = true;
    $("btnSaveProfilesCloud").textContent = "⏳ 正在写入 GitHub...";
    try {
      // 1. Read current profiles.json SHA
      const getRes = await fetch(`${apiBase}/contents/profiles.json`, { headers });
      if (!getRes.ok) throw new Error(`读取仓库失败 (HTTP ${getRes.status})，请检查 Token 权限`);
      const fileInfo = await getRes.json();

      // 2. Encode UTF-8 JSON to base64
      const jsonStr = JSON.stringify({ version: 2, profiles: draftProfiles }, null, 2) + "\n";
      const bytes = new TextEncoder().encode(jsonStr);
      let bin = "";
      bytes.forEach((b) => (bin += String.fromCharCode(b)));
      const contentB64 = btoa(bin);

      // 3. Commit updated profiles.json
      const putRes = await fetch(`${apiBase}/contents/profiles.json`, {
        method: "PUT",
        headers,
        body: JSON.stringify({
          message: "feat: update monitored products from mobile dashboard",
          content: contentB64,
          sha: fileInfo.sha,
          branch: "main",
        }),
      });
      if (!putRes.ok) {
        const err = await putRes.json().catch(() => ({}));
        throw new Error(err.message || `写入失败 (HTTP ${putRes.status})`);
      }

      // 4. Immediately trigger GitHub Actions cloud scan!
      await fetch(`${apiBase}/actions/workflows/monitor.yml/dispatches`, {
        method: "POST",
        headers,
        body: JSON.stringify({ ref: "main", inputs: { test_notify: false, send_digest: false } }),
      });

      $("profilesModal").classList.remove("open");
      showToast("✅ 已保存到 GitHub 并触发云端扫描！约 30~45 秒后点「拉取最新云端数据」即可看到新商品！", 5500);
      setTimeout(() => loadData(true), 35000);
    } catch (err) {
      showToast("❌ 保存失败: " + err.message, 4800);
    } finally {
      $("btnSaveProfilesCloud").disabled = false;
      $("btnSaveProfilesCloud").textContent = "☁️ 保存到 GitHub 并立即云端扫描";
    }
  }

  async function saveProfilesAction(syncCloud) {
    saveFormBackToDraft();
    if (!draftProfiles.length) {
      showToast("至少需要保留 1 个监控商品");
      return;
    }
    if (!isLocalServer) {
      await saveProfilesRemoteFromMobile();
      return;
    }

    const btn = syncCloud ? $("btnSaveProfilesCloud") : $("btnSaveProfilesLocal");
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = syncCloud ? "⏳ 保存、扫描并推送云端..." : "⏳ 保存并扫描中...";
    showToast("正在按新商品列表扫描雅虎日拍并正文排雷，请稍候...");
    try {
      const res = await fetch("/api/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profiles: draftProfiles, scan_now: true, sync_github: syncCloud }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "保存失败");
      if (data.snapshot) snapshot = data.snapshot;
      $("profilesModal").classList.remove("open");
      render();
      if (syncCloud) {
        showToast(data.sync?.ok ? "✅ " + data.sync.message : "⚠️ 本地已生效，云端推送失败: " + (data.sync?.message || ""), 5000);
      } else {
        showToast(`✅ 商品列表已更新！共扫到 ${snapshot?.summary?.total_clean ?? 0} 件有效商品`);
      }
    } catch (e) {
      showToast("❌ " + e.message, 4200);
    } finally {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }

  // ==================== GLOBAL SETTINGS MODAL ====================
  async function openSettings() {
    if (!isLocalServer) return;
    try {
      const res = await fetch("/api/config");
      fullConfig = await res.json();
      const cm = fullConfig.cost_model || {};
      const flt = fullConfig.filters || {};
      const nf = fullConfig.notifications || {};

      $("cfgSpread").value = cm.fx_spread_pct ?? 3.5;
      $("cfgDoorzoFee").value = cm.doorzo_fee_jpy ?? 300;
      $("cfgPollMin").value = fullConfig.poll_interval_minutes ?? 10;
      $("cfgCooldown").value = flt.alert_cooldown_minutes ?? 120;

      $("cfgBark").value = nf.bark_url || "";
      $("cfgNtfy").value = nf.ntfy_topic || "";
      $("cfgPushPlus").value = nf.pushplus_token || "";
      $("cfgServerChan").value = nf.serverchan_key || "";
      $("cfgFeishu").value = nf.feishu_webhook || "";
      $("cfgDingtalk").value = nf.dingtalk_webhook || "";
      $("cfgWinToast").checked = !!nf.windows_toast;
      $("settingsModal").classList.add("open");
    } catch (e) {
      showToast("加载配置失败: " + e.message);
    }
  }

  function readGlobalConfig() {
    const cfg = JSON.parse(JSON.stringify(fullConfig || {}));
    cfg.poll_interval_minutes = Math.max(2, Number($("cfgPollMin").value) || 10);
    cfg.cost_model = {
      ...(cfg.cost_model || {}),
      fx_spread_pct: Number($("cfgSpread").value) || 3.5,
      doorzo_fee_jpy: Number($("cfgDoorzoFee").value) || 300,
    };
    cfg.filters = {
      ...(cfg.filters || {}),
      alert_cooldown_minutes: Math.max(15, Number($("cfgCooldown").value) || 120),
    };
    cfg.notifications = {
      ...(cfg.notifications || {}),
      windows_toast: $("cfgWinToast").checked,
      bark_url: $("cfgBark").value.trim(),
      ntfy_topic: $("cfgNtfy").value.trim(),
      pushplus_token: $("cfgPushPlus").value.trim(),
      serverchan_key: $("cfgServerChan").value.trim(),
      feishu_webhook: $("cfgFeishu").value.trim(),
      dingtalk_webhook: $("cfgDingtalk").value.trim(),
    };
    return cfg;
  }

  // ==================== EVENT WIRING ====================
  $("profileBar").addEventListener("click", (e) => {
    const btn = e.target.closest(".profile-pill");
    if (!btn) return;
    const pid = btn.dataset.pid;
    if (pid === "__add__") {
      openProfileManager(true);
      return;
    }
    activeProfileId = pid;
    render();
  });

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
      const cat = inspectBtn.dataset.cat || "general";
      const pid = inspectBtn.dataset.pid || "";
      inspectBtn.disabled = true;
      inspectBtn.textContent = "⏳ 排雷中...";
      try {
        const res = await fetch("/api/inspect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ auction_id: aid, category: cat, profile_id: pid }),
        });
        const data = await res.json();
        if (data.ok && data.item) {
          const idx = (snapshot?.items || []).findIndex((x) => x.auction_id === aid && (!pid || x.profile_id === pid));
          if (idx >= 0) snapshot.items[idx] = data.item;
          const rep = data.report || {};
          if (rep.severe_tags && rep.severe_tags.length) {
            showToast(`⛔ 排雷拦截！正文检出硬伤: ${rep.severe_tags.join(" / ")}`, 4200);
          } else if (rep.moderate_tags && rep.moderate_tags.length) {
            showToast(`⚠️ 正文检出瑕疵: ${rep.moderate_tags.join(" / ")}`, 3600);
          } else {
            showToast("✅ 正文深查通过：未见明显硬件硬伤！", 3200);
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
      await toggleMark(actBtn.dataset.aid, actBtn.dataset.act === "star" ? "starred" : "ignored");
    }
  });

  // Header buttons
  $("btnScan").addEventListener("click", triggerManualScan);
  $("btnManageProfiles").addEventListener("click", () => openProfileManager(false));
  $("btnSettings").addEventListener("click", openSettings);
  $("btnSyncGh").addEventListener("click", async () => {
    $("btnSyncGh").disabled = true;
    $("btnSyncGh").textContent = "⏳ 同步中...";
    try {
      const res = await fetch("/api/sync-github", { method: "POST" });
      const data = await res.json();
      showToast(data.ok ? "✅ " + data.message : "❌ " + data.message, 4500);
    } catch (e) {
      showToast("同步失败: " + e.message);
    } finally {
      $("btnSyncGh").disabled = false;
      $("btnSyncGh").textContent = "☁️ 同步云端";
    }
  });

  // Profile manager events
  $("pmList").addEventListener("click", (e) => {
    const row = e.target.closest(".pm-item");
    if (!row) return;
    saveFormBackToDraft();
    loadDraftIntoForm(Number(row.dataset.pidx));
  });

  $("pmCategory").addEventListener("change", () => {
    const catId = $("pmCategory").value;
    const tpl = findTemplate(catId);
    $("pmIntlShip").value = tpl.intl_shipping_jpy;
    $("pmDomShip").value = tpl.default_domestic_shipping_jpy;
    $("pmTaxIncl").checked = !!tpl.tax_included_shipping;
    if (catId === "laptop") {
      $("pmAucCat").value = tpl.yahoo_category_id || "23412";
      $("pmG83GenBox").style.display = "none";
    }
    updateTemplateHint(catId);
  });

  $("btnNewProfile").addEventListener("click", () => {
    saveFormBackToDraft();
    addBlankDraftProfile();
  });

  $("btnApplyForm").addEventListener("click", () => {
    saveFormBackToDraft();
    showToast("✓ 已暂存该商品修改，点底部「保存」即可生效");
  });

  $("btnDeleteProfile").addEventListener("click", () => {
    if (draftProfiles.length <= 1) {
      showToast("⚠️ 至少需要保留 1 个监控商品");
      return;
    }
    const removed = draftProfiles.splice(selectedDraftIdx, 1)[0];
    showToast(`已移除「${removed.name}」，点底部保存后生效`);
    loadDraftIntoForm(Math.max(0, selectedDraftIdx - 1));
  });

  $("btnSavePat").addEventListener("click", () => {
    const v = $("ghPatInput").value.trim();
    if (!v) return showToast("请先粘贴 Token");
    localStorage.setItem("radar_gh_pat_v1", v);
    showToast("✅ 已保存在你本机浏览器里");
  });

  $("btnClosePm").addEventListener("click", () => $("profilesModal").classList.remove("open"));
  $("btnCancelPm").addEventListener("click", () => $("profilesModal").classList.remove("open"));
  $("btnSaveProfilesLocal").addEventListener("click", () => saveProfilesAction(false));
  $("btnSaveProfilesCloud").addEventListener("click", () => saveProfilesAction(true));

  // Global settings events
  $("btnCloseModal").addEventListener("click", () => $("settingsModal").classList.remove("open"));
  $("btnCancelModal").addEventListener("click", () => $("settingsModal").classList.remove("open"));
  $("btnSaveConfig").addEventListener("click", async () => {
    const cfg = readGlobalConfig();
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      });
      const data = await res.json();
      if (data.ok) {
        $("settingsModal").classList.remove("open");
        showToast("✅ 全局设置已保存！后台正在按新参数重新计算...");
        setTimeout(loadData, 3000);
      } else {
        showToast("保存失败: " + data.error);
      }
    } catch (e) {
      showToast("保存失败: " + e.message);
    }
  });

  $("btnTestNotify").addEventListener("click", async () => {
    const cfg = readGlobalConfig();
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
        showToast("⚠️ 请先勾选桌面通知，或填写至少一个推送通道", 3800);
        return;
      }
      showToast("推送结果 -> " + chs.map(([k, v]) => `${k}: ${v.ok ? "成功" : "失败"}`).join(" | "), 4500);
    } catch (e) {
      showToast("测试推送失败: " + e.message);
    }
  });

  // Auto refresh UI periodically AND when mobile tab wakes up
  loadData();
  setInterval(() => loadData(false), 60000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadData(false);
  });
})();
