"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const api = (p, opt) => fetch("/api" + p, opt);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ============ TOAST ============ */
let toastTimer = null;
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2500);
}

/* ============ MODAL ============ */
const ICONS = { info: "ⓘ", danger: "⚠", warn: "⚠", ok: "✔", question: "?" };
function closeModal() {
  $("#modalOverlay").hidden = true;
  $("#modalBody").innerHTML = "";
  $("#modalFoot").innerHTML = "";
}
function openModal({ kind = "info", title, bodyHtml, buttons = [] }) {
  const modal = $("#modalOverlay").querySelector(".modal");
  modal.className = "modal k-" + kind;
  $("#modalIcon").textContent = ICONS[kind] || "ⓘ";
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = bodyHtml;
  const foot = $("#modalFoot"); foot.innerHTML = "";
  buttons.forEach((b) => {
    const el = document.createElement("button");
    el.className = "btn " + (b.cls || "btn-ghost");
    el.textContent = b.label;
    el.onclick = async () => {
      try { if (b.onClick) await b.onClick(); if (b.close !== false) closeModal(); }
      catch (e) { toast(e.message || "Gagal", "err"); }
    };
    foot.appendChild(el);
  });
  $("#modalOverlay").hidden = false;
}
$("#modalClose").onclick = closeModal;
$("#modalOverlay").addEventListener("click", (e) => { if (e.target.id === "modalOverlay") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modalOverlay").hidden) closeModal(); });

/* ============ STEP 1: SOURCE TYPE PICKER ============ */
let activeType = null;

$$(".src-type-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const type = btn.dataset.type;

    // Toggle: klik yg sama = unselect
    if (activeType === type) {
      activeType = null;
      $$(".src-type-btn").forEach((b) => b.classList.remove("selected"));
      $$(".src-form").forEach((f) => f.hidden = true);
      return;
    }

    activeType = type;
    $$(".src-type-btn").forEach((b) => b.classList.toggle("selected", b.dataset.type === type));
    $$(".src-form").forEach((f) => f.hidden = f.dataset.type !== type);

    // Auto-focus name field
    const nameInput = document.getElementById(type + "-name");
    if (nameInput) setTimeout(() => nameInput.focus(), 100);
  });
});

/* ============ ADV TOGGLE (shared) ============ */
$$(".adv-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    const box = btn.closest(".panel").querySelector(".adv-box");
    box.hidden = !box.hidden;
    btn.classList.toggle("btn-primary", !box.hidden);
  });
});

function getAdv() {
  const adv = document.querySelector(".adv-box");
  return {
    mode: adv.querySelector(".f-mode").value,
    audio: adv.querySelector(".f-audio").value,
    fast_start: adv.querySelector(".f-fast").checked,
    low_latency: adv.querySelector(".f-lowlat").checked,
  };
}

/* ============ HEALTH ============ */
async function checkHealth() {
  try {
    const r = await fetch("/health");
    $("#healthDot").className = "dot " + (r.ok ? "ok" : "bad");
    $("#healthText").textContent = r.ok ? "ONLINE" : "ERROR";
  } catch {
    $("#healthDot").className = "dot bad";
    $("#healthText").textContent = "OFFLINE";
  }
}

/* ============ TABLE ============ */
function fmtMode(x) {
  let m = x.active_mode || x.mode;
  if (x.fast_start) m += " <span class='fast'>⚡fast</span>";
  return m;
}

function rowHtml(x) {
  const codec = x.source_codec
    ? `${esc(x.source_codec)}${x.width ? ` ${x.width}×${x.height}` : ""}`
    : "—";
  const err = x.last_error ? `<span class="err-text">${esc(x.last_error)}</span>` : "";
  let badge = "";
  if (x.original_url) badge = `<span class="badge yt" title="${esc(x.original_url)}">▶ YouTube</span>`;
  else if (x.source_type === "file") badge = `<span class="badge file" title="${esc(x.file_path || "")}">📁 ${esc(x.file_name || "MP4")}</span>`;
  else if (x.source_type === "hls") badge = `<span class="badge hls">📡 HLS</span>`;
  return `<tr>
    <td><span class="name">${esc(x.name)} ${badge}</span>${err}</td>
    <td><span class="badge ${x.status}">${x.status}</span></td>
    <td class="tag">${codec}</td>
    <td class="tag">${fmtMode(x)}</td>
    <td><span class="url">${esc(x.rtsp_url || "")}</span></td>
    <td class="num tag">${x.readers}</td>
    <td><div class="btnrow">
      <button class="btn btn-sm" data-act="copy"    data-id="${x.id}">COPY</button>
      <button class="btn btn-sm" data-act="edit"    data-id="${x.id}">EDIT</button>
      <button class="btn btn-sm btn-warn"   data-act="restart" data-id="${x.id}">↻</button>
      <button class="btn btn-sm btn-danger" data-act="delete"  data-id="${x.id}">✕</button>
    </div></td>
  </tr>`;
}

let CACHE = [];
async function refresh() {
  try {
    const data = await (await api("/sources")).json();
    CACHE = data;
    $("#count").textContent = data.length;
    $("#srcBody").innerHTML = data.length
      ? data.map(rowHtml).join("")
      : `<tr><td colspan="7" class="empty">No sources yet. Add one above.</td></tr>`;
  } catch (e) {
    $("#srcBody").innerHTML = `<tr><td colspan="7" class="empty">Failed to load: ${esc(e.message)}</td></tr>`;
  }
}

const byId = (id) => CACHE.find((s) => s.id === id);

/* ============ HLS FORM ============ */
$("#formHls").addEventListener("submit", async (e) => {
  e.preventDefault();
  const adv = getAdv();
  const body = {
    name: $("#hls-name").value.trim(),
    hls_url: $("#hls-url").value.trim(),
    source_type: "hls",
    mode: adv.mode,
    audio: adv.audio,
    fast_start: adv.fast_start,
    low_latency: adv.low_latency,
  };
  await submitSource(body);
});

/* ============ YOUTUBE FORM ============ */
$("#formYt").addEventListener("submit", async (e) => {
  e.preventDefault();
  const adv = getAdv();
  const body = {
    name: $("#yt-name").value.trim(),
    hls_url: $("#yt-url").value.trim(),
    source_type: "hls",
    mode: adv.mode,
    audio: adv.audio,
    fast_start: adv.fast_start,
    low_latency: adv.low_latency,
  };
  await submitSource(body);
});

/* ============ MP4 UPLOAD ============ */
const dz = $("#dropzone");
const dzInput = $("#mp4-file");
const dzHint = $("#dzHint");
const dzName = $("#dzName");

dzInput.addEventListener("change", () => {
  if (dzInput.files.length) {
    dzHint.hidden = true;
    dzName.hidden = false;
    dzName.textContent = dzInput.files[0].name + " (" + fmtSize(dzInput.files[0].size) + ")";
  }
});
dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dz-over"); });
dz.addEventListener("dragleave", () => { dz.classList.remove("dz-over"); });
dz.addEventListener("drop", (e) => {
  e.preventDefault(); dz.classList.remove("dz-over");
  if (e.dataTransfer.files.length) {
    dzInput.files = e.dataTransfer.files;
    dzHint.hidden = true; dzName.hidden = false;
    dzName.textContent = e.dataTransfer.files[0].name + " (" + fmtSize(e.dataTransfer.files[0].size) + ")";
  }
});

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + "B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + "KB";
  return (bytes / 1048576).toFixed(1) + "MB";
}

$("#btnUploadMp4").addEventListener("click", async () => {
  const name = $("#mp4-name").value.trim();
  const file = dzInput.files[0];
  if (!name) { toast("Nama harus diisi", "err"); return; }
  if (!file) { toast("Pilih file MP4", "err"); return; }
  if (file.size > 50 * 1024 * 1024) { toast("File maks 50MB!", "err"); return; }

  const adv = getAdv();
  const btn = $("#btnUploadMp4");
  btn.disabled = true;
  let _loadTimer = showLoading(btn);

  try {
    // Upload
    const fd = new FormData();
    fd.append("file", file);
    const upRes = await fetch("/api/upload", { method: "POST", body: fd });
    if (!upRes.ok) {
      const err = await upRes.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : `upload HTTP ${upRes.status}`);
    }
    const upData = await upRes.json();

    // Create source
    const body = {
      name: name,
      hls_url: upData.file_path,
      source_type: "file",
      file_path: upData.file_path,
      mode: adv.mode,
      audio: adv.audio,
      fast_start: adv.fast_start,
      low_latency: adv.low_latency,
    };
    const r = await api("/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : `HTTP ${r.status}`);
    }

    // Reset
    $("#mp4-name").value = "";
    dzInput.value = ""; dzHint.hidden = false; dzName.hidden = true;
    document.querySelector(".adv-box").hidden = true;
    $$(".adv-toggle").forEach((b) => b.classList.remove("btn-primary"));
    await refresh();
    toast("File + stream added ✔", "ok");
  } catch (e) {
    openModal({ kind: "danger", title: "GAGAL", bodyHtml: `<p>${esc(e.message)}</p>`, buttons: [{ label: "TUTUP", cls: "btn-ghost" }] });
  } finally {
    hideLoading(btn, _loadTimer);
    btn.disabled = false;
  }
});

/* ============ SUBMIT HELPER ============ */
async function submitSource(body) {
  const form = document.querySelector(".src-form:not([hidden]) form") || document.querySelector(".src-form:not([hidden])");
  const btn = form ? form.querySelector(".btn-primary") : null;
  if (btn) btn.disabled = true;
  let _loadingTimer = showLoading(btn);

  try {
    const r = await api("/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : `HTTP ${r.status}`);
    }
    const created = await r.json();

    // Reset form
    const srcType = body.source_type === "file" ? "mp4" : (body.original_url ? "youtube" : "hls");
    const nameInput = document.getElementById(srcType + "-name");
    const urlInput = document.getElementById(srcType + "-url");
    if (nameInput) nameInput.value = "";
    if (urlInput) urlInput.value = "";
    // Reset advanced
    const advBox = document.querySelector(".adv-box");
    if (advBox) advBox.hidden = true;
    $$(".adv-toggle").forEach((b) => b.classList.remove("btn-primary"));

    await refresh();
    if (created.last_error) {
      openModal({ kind: "warn", title: "DITAMBAHKAN (dengan peringatan)", bodyHtml: `<p>Source <code>${esc(created.name)}</code> dibuat, but there is a note:</p><p class="hint">${esc(created.last_error)}</p>`, buttons: [{ label: "OK", cls: "btn-primary" }] });
    } else {
      toast("Source added ✔", "ok");
    }
  } catch (e) {
    openModal({ kind: "danger", title: "GAGAL MENAMBAH", bodyHtml: `<p>${esc(e.message)}</p>`, buttons: [{ label: "TUTUP", cls: "btn-ghost" }] });
  } finally {
    hideLoading(btn, _loadingTimer);
    if (btn) btn.disabled = false;
  }
}


/* ============ LOADING ANIMATION ============ */
function showLoading(btn) {
  if (!btn) return null;
  const orig = btn.innerHTML || btn.textContent;
  btn.dataset.origText = orig;
  let dots = 0;
  const timer = setInterval(() => {
    dots = (dots + 1) % 4;
    btn.innerHTML = '<span class="spin"></span> ' + (orig.replace(/<[^>]*>/g, '')) + '.'.repeat(dots);
  }, 400);
  return timer;
}

function hideLoading(btn, timer) {
  if (timer) clearInterval(timer);
  if (btn && btn.dataset.origText) {
    btn.innerHTML = btn.dataset.origText;
  }
}

/* ============ ACTIONS ============ */
$("#srcBody").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const act = btn.dataset.act;
  const src = byId(btn.dataset.id);
  if (!src) return;
  ({ copy: doCopy, edit: doEdit, restart: doRestart, delete: doDelete }[act])(src);
});

function doCopy(src) {
  const text = src.rtsp_url || "";
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text);
    toast("RTSP URL copied ✔", "ok"); return;
  }
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.left = "-9999px";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); toast("RTSP URL copied ✔", "ok"); }
  catch { toast("Failed to copy.", "err"); }
  document.body.removeChild(ta);
}

function doRestart(src) {
  openModal({ kind: "warn", title: "RESTART STREAM", bodyHtml: `<p>Restart stream <code>${esc(src.name)}</code>?</p>`, buttons: [
    { label: "BATAL", cls: "btn-ghost" },
    { label: "RESTART", cls: "btn-warn", close: false, onClick: async () => {
        await action(`/sources/${src.id}/restart`, "POST");
        toast(`'${src.name}' restarted ✔`, "ok"); closeModal(); refresh();
    }},
  ]});
}

function doDelete(src) {
  openModal({ kind: "danger", title: "HAPUS SUMBER", bodyHtml: `<p>Hapus <code>${esc(src.name)}</code>?</p><p class="hint">RTSP tidak akan bisa diakses lagi.</p>`, buttons: [
    { label: "BATAL", cls: "btn-ghost" },
    { label: "HAPUS", cls: "btn-danger", close: false, onClick: async () => {
        await action(`/sources/${src.id}`, "DELETE");
        toast(`'${src.name}' deleted`, "ok"); closeModal(); refresh();
    }},
  ]});
}

function doEdit(src) {
  const opt = (v, cur) => `${v}${v === cur ? " selected" : ""}`;
  const isFile = src.source_type === "file";
  let urlFieldHtml;
  if (isFile) {
    urlFieldHtml = `<div class="field"><label>FILE</label><input id="e-url" type="text" value="${esc(src.file_name || src.file_path || "")}" readonly style="opacity:0.6;" /></div><p class="hint">File tidak bisa diganti via edit. Hapus & upload ulang.</p>`;
  } else {
    const origHtml = src.original_url ? `<div style="margin-bottom:8px;font-size:11px;color:var(--muted);"><span style="display:block;font-size:10px;letter-spacing:1px;color:var(--dim);">YOUTUBE ASLI</span><span class="url">${esc(src.original_url)}</span></div>` : "";
    urlFieldHtml = `<div class="field"><label>URL</label><input id="e-url" type="url" value="${esc(src.original_url || src.hls_url)}" /></div>${origHtml}`;
  }
  openModal({ kind: "info", title: `EDIT — ${esc(src.name)}`, bodyHtml: `
    ${urlFieldHtml}
    <div style="background:var(--surface-2);padding:12px;border:1px solid var(--line);margin:12px 0;">
      <p style="margin:0 0 10px 0;font-size:11px;color:var(--muted);letter-spacing:1px;">OPSI LANJUTAN</p>
      <div class="field"><label>MODE</label><select id="e-mode">
        <option ${opt("auto", src.mode)}>auto (deteksi codec)</option>
        <option ${opt("copy", src.mode)}>copy (passthrough)</option>
        <option ${opt("transcode", src.mode)}>transcode → H.264</option>
      </select></div>
      <div class="field"><label>AUDIO</label><select id="e-audio">
        <option ${opt("aac", src.audio)}>aac</option>
        <option ${opt("copy", src.audio)}>copy</option>
        <option ${opt("drop", src.audio)}>drop (tanpa audio)</option>
      </select></div>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:10px;"><input type="checkbox" id="e-fast" ${src.fast_start ? "checked" : ""} /><span style="font-size:11px;color:var(--text);">FAST START <em style="color:var(--dim);font-style:normal;font-size:10px;">(instant play)</em></span></label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:8px;"><input type="checkbox" id="e-lowlat" ${src.low_latency ? "checked" : ""} /><span style="font-size:11px;color:var(--text);">LOW LATENCY <em style="color:var(--dim);font-style:normal;font-size:10px;">(live-edge)</em></span></label>
    </div>`,
    buttons: [
      { label: "BATAL", cls: "btn-ghost" },
      { label: "SIMPAN", cls: "btn-primary", close: false, onClick: async () => {
          await action(`/sources/${src.id}`, "PATCH", {
            hls_url: $("#e-url").value.trim(),
            mode: $("#e-mode").value,
            audio: $("#e-audio").value,
            fast_start: $("#e-fast").checked,
            low_latency: $("#e-lowlat").checked,
          });
          toast(`'${src.name}' updated ✔`, "ok"); closeModal(); refresh();
      }},
    ],
  });
}

async function action(path, method, body) {
  const r = await api(path, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok && r.status !== 204) {
    const err = await r.json().catch(() => ({}));
    throw new Error(typeof err.detail === "string" ? err.detail : `HTTP ${r.status}`);
  }
}


/* ============ ABOUT TOGGLE ============ */
$("#aboutToggle").onclick = function() {
  const body = $("#aboutBody");
  const arrow = this.querySelector(".about-arrow");
  body.hidden = !body.hidden;
  arrow.textContent = body.hidden ? "\u25b6" : "\u25bc";
};

/* ============ AUTO-REFRESH ============ */
let timer = null;
function setupAuto() {
  if (timer) clearInterval(timer);
  if ($("#autoRefresh").checked) timer = setInterval(refresh, 3000);
}
$("#autoRefresh").addEventListener("change", setupAuto);

checkHealth();
refresh();
setupAuto();
setInterval(checkHealth, 5000);
