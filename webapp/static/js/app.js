/* =========================================================
   Reality Watcher – frontend application
   ========================================================= */
"use strict";

// ── State ────────────────────────────────────────────────────────────────
const state = {
  filters: { dispo: [], price_min: "", price_max: "", area_min: "", area_max: "", q: "", sort: "newest", page: 1 },
  activeConfigId: null,   // null = "Všechny"
  configs: [],            // loaded search configs for tabs
  total: 0,
  selectedId: null,
  galleryIndex: 0,
  galleryImages: [],
};
const PAGE_SIZE = 40;

// ── Formatters ───────────────────────────────────────────────────────────
const fmtPrice  = n => n == null ? "–" : n.toLocaleString("cs-CZ") + " Kč";
const fmtArea   = n => n == null ? "–" : n + " m²";
const fmtPriceM2 = n => n == null ? "–" : n.toLocaleString("cs-CZ") + " Kč/m²";
function timeAgo(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return "právě teď";
  if (s < 3600) return Math.floor(s / 60) + " min";
  if (s < 86400) return Math.floor(s / 3600) + " h";
  return Math.floor(s / 86400) + " d";
}
function getCsrf() {
  for (const c of document.cookie.split(";")) {
    const [k, v] = c.trim().split("=");
    if (k === "csrftoken") return decodeURIComponent(v);
  }
  return "";
}
function escHtml(s) {
  if (!s) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
async function apiFetch(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrf(), ...opts.headers }, ...opts });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.error || res.statusText); }
  return res.json();
}

// ── Drag-to-resize ───────────────────────────────────────────────────────
function initDragResize() {
  const sidebar  = document.getElementById("sidebar");
  const detail   = document.getElementById("detail-panel");
  const body     = document.getElementById("app-body");

  function startDrag(handle, onMove) {
    handle.addEventListener("mousedown", e => {
      e.preventDefault();
      handle.classList.add("dragging");
      body.style.userSelect = "none";
      const move = ev => onMove(ev);
      const up   = () => {
        handle.classList.remove("dragging");
        body.style.userSelect = "";
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
  }

  // Left handle resizes sidebar
  startDrag(document.getElementById("drag-left"), ev => {
    const w = Math.min(Math.max(ev.clientX, 180), 500);
    sidebar.style.flex = `0 0 ${w}px`;
    sidebar.style.width = w + "px";
  });

  // Right handle resizes detail panel
  startDrag(document.getElementById("drag-right"), ev => {
    const bodyRect = body.getBoundingClientRect();
    const w = Math.min(Math.max(bodyRect.right - ev.clientX, 260), 700);
    detail.style.flex = `0 0 ${w}px`;
    detail.style.width = w + "px";
  });
}

// ── Watcher Tabs ─────────────────────────────────────────────────────────
async function loadTabs() {
  const data = await apiFetch("/api/search-configs/");
  state.configs = data.results;
  // Auto-select first watcher on initial load
  if (state.activeConfigId === null && state.configs.length > 0) {
    state.activeConfigId = state.configs[0].id;
  }
  renderTabs();
}

function renderTabs() {
  const el = document.getElementById("watcher-tabs");
  let html = "";
  for (const c of state.configs) {
    const active = state.activeConfigId === c.id ? "active" : "";
    html += `<button class="tab-btn ${active}" data-id="${c.id}">${escHtml(c.name)} <span class="tab-count">${c.listing_count || 0}</span></button>`;
  }
  // "+" add-watcher tab
  html += `<button class="tab-btn tab-add" id="tab-add-btn" title="Přidat sledování">＋</button>`;
  el.innerHTML = html;
  el.querySelectorAll(".tab-btn[data-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeConfigId = Number(btn.dataset.id);
      state.filters.page = 1;
      renderTabs();
      loadListings();
    });
  });
  const addBtn = document.getElementById("tab-add-btn");
  if (addBtn) addBtn.addEventListener("click", () => openModal("modal-add-config"));
}

// ── Filter options ───────────────────────────────────────────────────────
async function loadFilterOptions() {
  const data = await apiFetch("/api/filter-options/");
  const dispoEl = document.getElementById("filter-dispo");
  dispoEl.innerHTML = data.dispo.map(d =>
    `<label><input type="checkbox" class="cb-dispo" value="${escHtml(d)}" /> ${escHtml(d)}</label>`
  ).join("");
  document.querySelectorAll(".cb-dispo").forEach(cb => cb.addEventListener("change", onFilterChange));
}

function onFilterChange() {
  state.filters.dispo    = [...document.querySelectorAll(".cb-dispo:checked")].map(e => e.value);
  state.filters.price_min = document.getElementById("price-min").value;
  state.filters.price_max = document.getElementById("price-max").value;
  state.filters.area_min  = document.getElementById("area-min").value;
  state.filters.area_max  = document.getElementById("area-max").value;
  state.filters.q         = document.getElementById("text-search").value;
  state.filters.sort      = document.getElementById("sort-select").value;
  state.filters.page = 1;
  loadListings();
}

// ── Listing list ─────────────────────────────────────────────────────────
function buildQuery() {
  const f = state.filters;
  const p = new URLSearchParams();
  f.dispo.forEach(d => p.append("dispo", d));
  if (f.price_min) p.set("price_min", f.price_min);
  if (f.price_max) p.set("price_max", f.price_max);
  if (f.area_min)  p.set("area_min",  f.area_min);
  if (f.area_max)  p.set("area_max",  f.area_max);
  if (f.q)         p.set("q", f.q);
  if (state.activeConfigId) p.set("config_id", state.activeConfigId);
  p.set("sort", f.sort);
  p.set("page", f.page);
  return p.toString();
}

async function loadListings() {
  const data = await apiFetch("/api/listings/?" + buildQuery());
  state.total = data.total;
  document.getElementById("listing-count").textContent =
    data.total ? `${data.total.toLocaleString("cs-CZ")} inzerátů` : "";

  const cards  = document.getElementById("listing-cards");
  const empty  = document.getElementById("empty-state");
  if (!data.results.length) {
    cards.innerHTML = "";
    empty.classList.remove("hidden");
  } else {
    empty.classList.add("hidden");
    cards.innerHTML = data.results.map(renderCard).join("");
    document.querySelectorAll(".listing-card").forEach(c =>
      c.addEventListener("click", () => openDetail(Number(c.dataset.id)))
    );
  }
  renderPagination(data.total, data.page, data.page_size);
}

function renderCard(l) {

  const active = l.id === state.selectedId ? "active" : "";

  const badge = l.has_analysis ? '<span class="card-analysis-badge">AI ✓</span>' : "";

  const title = `${l.object_type} - ${l.locality}`;

  return `

    <div class="listing-card ${active}" data-id="${l.id}">

      <div class="card-title">${escHtml(title)}</div>

      <div class="card-price">${fmtPrice(l.price_czk)}</div>

      <div class="card-tags">

        ${l.dispo ? `<span class="chip dispo">${escHtml(l.dispo)}</span>` : ""}

        ${l.offer_type ? `<span class="chip offer-type">${escHtml(l.offer_type)}</span>` : ""}

        ${l.area_m2 ? `<span class="chip area">${fmtArea(l.area_m2)}</span>` : ""}

      </div>

      <div class="card-footer">

        <span class="card-age">${timeAgo(l.first_seen)}</span>

        ${badge}

      </div>

    </div>`;

}

// ── Pagination ────────────────────────────────────────────────────────────
function renderPagination(total, page, pageSize) {
  const pages = Math.ceil(total / pageSize);
  const el = document.getElementById("pagination");
  if (pages <= 1) { el.innerHTML = ""; return; }
  let h = page > 1 ? `<button class="page-btn" data-p="${page-1}">‹</button>` : "";
  for (let p = Math.max(1,page-2); p <= Math.min(pages,page+2); p++)
    h += `<button class="page-btn ${p===page?"active":""}" data-p="${p}">${p}</button>`;
  if (page < pages) h += `<button class="page-btn" data-p="${page+1}">›</button>`;
  el.innerHTML = h;
  el.querySelectorAll(".page-btn").forEach(b =>
    b.addEventListener("click", () => { state.filters.page = Number(b.dataset.p); loadListings(); })
  );
}

// ── Detail panel ──────────────────────────────────────────────────────────
async function openDetail(id) {
  state.selectedId = id;
  document.querySelectorAll(".listing-card").forEach(c =>
    c.classList.toggle("active", Number(c.dataset.id) === id)
  );
  const placeholder = document.getElementById("detail-placeholder");
  const content     = document.getElementById("detail-content");
  placeholder.classList.add("hidden");
  content.classList.remove("hidden");
  content.innerHTML = `<div style="padding:20px;text-align:center"><span class="spinner"></span></div>`;

  const l = await apiFetch(`/api/listings/${id}/`);
  state.galleryImages = l.images || [];
  state.galleryIndex  = 0;
  content.innerHTML = renderDetail(l);
  attachDetailEvents(id, l);
}

function renderContact(c) {
  if (!c || (!c.name && !c.phone && !c.agency)) return "";
  const rows = [];
  if (c.name)   rows.push(`<span class="contact-label">Prodejce</span><span class="contact-value">${escHtml(c.name)}</span>`);
  if (c.agency) rows.push(`<span class="contact-label">Agentura</span><span class="contact-value">${escHtml(c.agency)}</span>`);
  if (c.phone)  rows.push(`<span class="contact-label">Telefon</span><span class="contact-value"><a href="tel:${escHtml(c.phone.replace(/\s/g,''))}">${escHtml(c.phone)}</a></span>`);
  return `<div class="detail-contact">${rows.map(r=>`<div class="contact-row">${r}</div>`).join("")}</div>`;
}

function renderDetail(l) {
  return `
    ${renderGallery(l.images || [])}
    <div class="detail-body">
      <div class="detail-header">
        <div class="detail-price">${fmtPrice(l.price_czk)}</div>
        <div class="detail-subtitle">${escHtml(l.title)}</div>
      </div>
      <div class="detail-chips">
        ${l.dispo       ? `<span class="chip dispo">${escHtml(l.dispo)}</span>` : ""}
        ${l.area_m2     ? `<span class="chip area">${fmtArea(l.area_m2)}</span>` : ""}
        ${l.locality    ? `<span class="chip locality">${escHtml(l.locality)}</span>` : ""}
        ${l.price_per_m2? `<span class="chip price-m2">${fmtPriceM2(l.price_per_m2)}</span>` : ""}
      </div>
      <a class="detail-link" href="${escHtml(l.url)}" target="_blank" rel="noopener">Otevřít na Sreality.cz ↗</a>
      ${renderContact(l.contact_info)}
      ${l.description ? `
        <div class="detail-section">
          <div class="detail-section-title">Popis</div>
          <div class="detail-description">${l.description.split("\n").map(line => escHtml(line.trim())).filter(Boolean).join("<br>")}</div>
        </div>` : ""}
      ${l.analysis
        ? renderAnalysis(l.analysis)
        : `<button class="btn btn-primary btn-analyze" id="btn-analyze">Analyzovat s AI</button>`}
    </div>`;
}

// ── Image gallery ─────────────────────────────────────────────────────────
function renderGallery(images) {
  if (!images || !images.length) {
    return `<div class="detail-gallery"><div class="gallery-no-image">Žádné obrázky</div></div>`;
  }
  const idx = state.galleryIndex;
  const total = images.length;
  return `
    <div class="detail-gallery">
      <img src="${escHtml(images[idx])}" alt="Foto ${idx+1}" onerror="this.style.display='none'"/>
      ${total > 1 ? `<button class="gallery-nav gallery-prev" id="gallery-prev">&#8249;</button>` : ""}
      ${total > 1 ? `<button class="gallery-nav gallery-next" id="gallery-next">&#8250;</button>` : ""}
      ${total > 1 ? `<span class="gallery-counter">${idx+1} / ${total}</span>` : ""}
    </div>`;
}

function attachDetailEvents(id, listing) {
  // Gallery navigation
  const prev = document.getElementById("gallery-prev");
  const next = document.getElementById("gallery-next");
  if (prev) prev.addEventListener("click", () => {
    state.galleryIndex = (state.galleryIndex - 1 + state.galleryImages.length) % state.galleryImages.length;
    refreshGallery();
  });
  if (next) next.addEventListener("click", () => {
    state.galleryIndex = (state.galleryIndex + 1) % state.galleryImages.length;
    refreshGallery();
  });

  // Analyze button
  const analyzeBtn = document.getElementById("btn-analyze");
  if (analyzeBtn) analyzeBtn.addEventListener("click", () => runAnalysis(id, listing));
}

function refreshGallery() {
  const galleryEl = document.querySelector(".detail-gallery");
  if (galleryEl) galleryEl.outerHTML; // can't do partial replace easily
  // re-render just gallery portion
  const content = document.getElementById("detail-content");
  const gallery = content.querySelector(".detail-gallery");
  if (gallery) {
    const tmp = document.createElement("div");
    tmp.innerHTML = renderGallery(state.galleryImages);
    gallery.replaceWith(tmp.firstElementChild);
    attachDetailEvents(state.selectedId, null);
  }
}

// ── AI Analysis ───────────────────────────────────────────────────────────
function renderAnalysis(a) {
  if (!a) return "";
  const vLabel = { "podhodnocená":"Podhodnocená","odpovídající":"Odpovídající","nadhodnocená":"Nadhodnocená","nelze_posoudit":"Nelze posoudit" };
  const vClass = { "podhodnocená":"verdict-undervalued","odpovídající":"verdict-fair","nadhodnocená":"verdict-overvalued" };
  const pa = a.price_assessment || {};
  const verdict = pa.verdict || "nelze_posoudit";
  const conf = pa.confidence ? ` (jistota: ${pa.confidence}/5)` : "";
  const pr = pa.price_per_m2_estimate;
  const priceRange = pr ? `Odh. rozpětí: ${(pr.expected_range_min||0).toLocaleString("cs-CZ")} – ${(pr.expected_range_max||0).toLocaleString("cs-CZ")} Kč/m²` : "";

  const flags = (a.red_flags||[]).map(f =>
    `<div class="flag-item"><span class="flag-severity sev-${f.severity}">${f.severity}/5</span><span><strong>${escHtml(f.label)}</strong>${f.comment?" – "+escHtml(f.comment):""}</span></div>`
  ).join("");
  const missing = (a.missing_critical_info||[]).map(m =>
    `<div class="flag-item"><span class="flag-severity sev-${m.importance}">${m.importance}/5</span><span><strong>${escHtml(m.label)}</strong>${m.comment?" – "+escHtml(m.comment):""}</span></div>`
  ).join("");
  const checklist = (a.checklist_for_viewing||[]).map(c =>
    `<div class="checklist-item">${escHtml(c)}</div>`
  ).join("");
  const comp = a.comparison || {};
  const pros = (comp.key_pros||[]).map(p=>`<div class="checklist-item">${escHtml(p)}</div>`).join("");
  const cons = (comp.key_cons||[]).map(c=>`<div class="checklist-item">${escHtml(c)}</div>`).join("");

  return `
    <div class="analysis-section">
      <div class="detail-section-title">AI Analýza</div>
      <div class="analysis-verdict ${vClass[verdict]||'verdict-unknown'}">${vLabel[verdict]||verdict}${conf}</div>
      ${priceRange ? `<div class="price-range">${priceRange}</div>` : ""}
      ${pa.comment ? `<div class="analysis-comment">${escHtml(pa.comment)}</div>` : ""}
      ${a.overall_comment ? `<div class="analysis-comment">${escHtml(a.overall_comment)}</div>` : ""}
      ${flags   ? `<div class="analysis-block"><div class="analysis-block-title">Red flags</div>${flags}</div>` : ""}
      ${missing ? `<div class="analysis-block"><div class="analysis-block-title">Chybějící info</div>${missing}</div>` : ""}
      ${(pros||cons) ? `
        <div class="analysis-block">
          <div class="analysis-block-title">Srovnání${comp.comment?" – "+escHtml(comp.comment):""}</div>
          ${pros ? `<div style="color:#2a6b3a;font-size:11px;font-weight:700;margin:4px 0 2px">Plusy</div>${pros}` : ""}
          ${cons ? `<div style="color:#e05252;font-size:11px;font-weight:700;margin:6px 0 2px">Minusy</div>${cons}` : ""}
        </div>` : ""}
      ${checklist ? `<div class="analysis-block"><div class="analysis-block-title">Checklist na prohlídku</div>${checklist}</div>` : ""}
    </div>`;
}

async function runAnalysis(id, listing) {
  const btn = document.getElementById("btn-analyze");
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Analyzuji…'; }
  try {
    const data = await apiFetch(`/api/listings/${id}/analyze/`, { method: "POST" });
    const content = document.getElementById("detail-content");
    const l = { ...(listing || {}), analysis: data.analysis };
    state.galleryImages = l.images || [];
    content.innerHTML = renderDetail(l);
    attachDetailEvents(id, l);
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = "Chyba – zkusit znovu"; }
    alert("Analýza selhala: " + err.message);
  }
}

// ── Search config modals ──────────────────────────────────────────────────
const openModal  = id => document.getElementById(id).classList.remove("hidden");
const closeModal = id => document.getElementById(id).classList.add("hidden");

document.getElementById("btn-cfg-cancel").addEventListener("click", () => closeModal("modal-add-config"));

document.getElementById("btn-cfg-save").addEventListener("click", async () => {
  const name     = document.getElementById("cfg-name").value.trim();
  const url      = document.getElementById("cfg-url").value.trim();
  const interval = document.getElementById("cfg-interval").value;
  const errEl    = document.getElementById("cfg-error");
  if (!name || !url) { errEl.textContent = "Název a URL jsou povinné."; errEl.classList.remove("hidden"); return; }
  try {
    await apiFetch("/api/search-configs/", { method: "POST", body: JSON.stringify({ name, url, interval_sec: Number(interval) }) });
    closeModal("modal-add-config");
    ["cfg-name","cfg-url"].forEach(id => document.getElementById(id).value = "");
    document.getElementById("cfg-interval").value = "300";
    errEl.classList.add("hidden");
    await loadTabs();
    await loadFilterOptions();
    await loadListings();
  } catch (err) { errEl.textContent = err.message; errEl.classList.remove("hidden"); }
});

document.getElementById("btn-manage-configs").addEventListener("click", async () => {
  await renderConfigList();
  openModal("modal-manage-configs");
});
document.getElementById("btn-manage-close").addEventListener("click", () => closeModal("modal-manage-configs"));

async function renderConfigList() {
  const el = document.getElementById("config-list-content");
  el.innerHTML = '<div style="text-align:center;padding:20px"><span class="spinner"></span></div>';
  const data = await apiFetch("/api/search-configs/");
  if (!data.results.length) {
    el.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px">Žádné zdroje.</p>';
    return;
  }
  el.innerHTML = data.results.map(c => `
    <div class="config-row">
      <div class="config-info">
        <div class="config-name">${escHtml(c.name)}</div>
        <div class="config-url">${escHtml(c.url)}</div>
        <div class="config-meta">Interval: ${c.interval_sec}s · Inzerátů: ${c.listing_count||0} · Poslední scrape: ${c.last_scraped ? new Date(c.last_scraped).toLocaleString("cs-CZ") : "nikdy"}</div>
      </div>
      <div class="config-actions">
        <button class="btn btn-secondary btn-scrape-now" data-id="${c.id}">▶ Teď</button>
        <button class="btn btn-danger btn-delete-config" data-id="${c.id}">Smazat</button>
      </div>
    </div>`).join("");

  el.querySelectorAll(".btn-delete-config").forEach(btn => btn.addEventListener("click", async () => {
    if (!confirm("Smazat tento zdroj?")) return;
    await apiFetch(`/api/search-configs/${btn.dataset.id}/`, { method: "DELETE" });
    if (state.activeConfigId === Number(btn.dataset.id)) state.activeConfigId = null;
    await renderConfigList();
    await loadTabs();
    await loadFilterOptions();
    loadListings();
  }));

  el.querySelectorAll(".btn-scrape-now").forEach(btn => btn.addEventListener("click", async () => {
    btn.disabled = true; btn.textContent = "…";
    try {
      const res = await apiFetch(`/api/search-configs/${btn.dataset.id}/scrape-now/`, { method: "POST" });
      btn.textContent = `+${res.new_listings}`;
      await loadTabs();
      await loadFilterOptions();
      loadListings();
    } catch (err) { btn.textContent = "Chyba"; alert(err.message); }
  }));
}

// ── Filters reset ─────────────────────────────────────────────────────────
document.getElementById("btn-reset-filters").addEventListener("click", () => {
  document.querySelectorAll(".cb-dispo").forEach(cb => cb.checked = false);
  ["price-min","price-max","area-min","area-max","text-search"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("sort-select").value = "newest";
  state.filters = { dispo:[], price_min:"", price_max:"", area_min:"", area_max:"", q:"", sort:"newest", page:1 };
  loadListings();
});
["price-min","price-max","area-min","area-max"].forEach(id =>
  document.getElementById(id).addEventListener("change", onFilterChange)
);
document.getElementById("sort-select").addEventListener("change", onFilterChange);
let _searchTimer;
document.getElementById("text-search").addEventListener("input", () => {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(onFilterChange, 400);
});

// Close modals on backdrop click
document.querySelectorAll(".modal-overlay").forEach(o =>
  o.addEventListener("click", e => { if (e.target === o) o.classList.add("hidden"); })
);

// ── Init ─────────────────────────────────────────────────────────────────
(async function init() {
  initDragResize();
  await Promise.all([loadTabs(), loadFilterOptions()]);
  await loadListings();
})();
