"use strict";

const $ = (s) => document.querySelector(s);
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

/**
 * openModal({ kind, title, bodyHtml, buttons:[{label,cls,onClick,close}] })
 */
function openModal({ kind = "info", title, bodyHtml, buttons = [] }) {
  const modal = $("#modalOverlay").querySelector(".modal");
  modal.className = "modal k-" + kind;
  $("#modalIcon").textContent = ICONS[kind] || "ⓘ";
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = bodyHtml;
  
  const foot = $("#modalFoot");
  foot.innerHTML = "";
  
  buttons.forEach((b) => {
    const el = document.createElement("button");
    el.className = "btn " + (b.cls || "btn-ghost");
    el.textContent = b.label;
    el.onclick = async () => {
      try {
        if (b.onClick) await b.onClick();
        if (b.close !== false) closeModal();
      } catch (e) {
        toast(e.message || "Gagal", "err");
      }
    };
    foot.appendChild(el);
  });
  
  $("#modalOverlay").hidden = false;
}

$("#modalClose").onclick = closeModal;
$("#modalOverlay").addEventListener("click", (e) => {
  if (e.target.id === "modalOverlay") closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#modalOverlay").hidden) closeModal();
});

/* ============ INIT ============ */
document.addEventListener("DOMContentLoaded", () => {
  closeModal(); // Ensure modal is hidden at startup
});
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
  return `<tr>
    <td><span class="name">${esc(x.name)}</span>${err}</td>
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
      : `<tr><td colspan="7" class="empty">Belum ada sumber. Tambahkan di atas.</td></tr>`;
  } catch (e) {
    $("#srcBody").innerHTML = `<tr><td colspan="7" class="empty">Gagal memuat: ${esc(e.message)}</td></tr>`;
  }
}

const byId = (id) => CACHE.find((s) => s.id === id);

/* ============ ADD (form sederhana) ============ */
$("#advToggle").onclick = () => {
  const b = $("#advBox");
  b.hidden = !b.hidden;
  $("#advToggle").classList.toggle("btn-primary", !b.hidden);
};

$("#addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    name: $("#f-name").value.trim(),
    hls_url: $("#f-url").value.trim(),
    mode: $("#f-mode").value,
    audio: $("#f-audio").value,
    fast_start: $("#f-fast").checked,
    low_latency: $("#f-lowlat").checked,
  };
  const btn = e.submitter;
  btn.disabled = true;
  toast("Memproses (ffprobe…)");
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
    $("#addForm").reset();
    $("#advBox").hidden = true;
    $("#advToggle").classList.remove("btn-primary");
    await refresh();
    if (created.last_error) {
      openModal({
        kind: "warn", title: "DITAMBAHKAN (dengan peringatan)",
        bodyHtml: `<p>Sumber <code>${esc(created.name)}</code> dibuat, tapi ada catatan:</p>
                   <p class="hint">${esc(created.last_error)}</p>`,
        buttons: [{ label: "OK", cls: "btn-primary" }],
      });
    } else {
      toast("Sumber ditambahkan ✔", "ok");
    }
  } catch (e) {
    openModal({
      kind: "danger", title: "GAGAL MENAMBAH",
      bodyHtml: `<p>${esc(e.message)}</p>`,
      buttons: [{ label: "TUTUP", cls: "btn-ghost" }],
    });
  } finally {
    btn.disabled = false;
  }
});

/* ============ ACTIONS (event delegation) ============ */
$("#srcBody").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const act = btn.dataset.act;
  const src = byId(btn.dataset.id);
  if (!src) return;
  ({ copy: doCopy, edit: doEdit, restart: doRestart, delete: doDelete }[act])(src);
});

function doCopy(src) {
  navigator.clipboard.writeText(src.rtsp_url || "");
  toast("URL RTSP disalin ✔", "ok");
}

function doRestart(src) {
  openModal({
    kind: "warn", title: "RESTART STREAM",
    bodyHtml: `<p>Restart stream <code>${esc(src.name)}</code>? Koneksi klien yang sedang menonton akan terputus sesaat.</p>`,
    buttons: [
      { label: "BATAL", cls: "btn-ghost" },
      { label: "RESTART", cls: "btn-warn", close: false, onClick: async () => {
          await action(`/sources/${src.id}/restart`, "POST");
          toast(`'${src.name}' direstart ✔`, "ok");
          closeModal(); refresh();
        } },
    ],
  });
}

function doDelete(src) {
  openModal({
    kind: "danger", title: "HAPUS SUMBER",
    bodyHtml: `<p>Hapus sumber <code>${esc(src.name)}</code> secara permanen?</p>
               <p class="hint">URL <code>${esc(src.rtsp_url)}</code> tidak akan bisa diakses lagi.</p>`,
    buttons: [
      { label: "BATAL", cls: "btn-ghost" },
      { label: "HAPUS", cls: "btn-danger", close: false, onClick: async () => {
          await action(`/sources/${src.id}`, "DELETE");
          toast(`'${src.name}' dihapus`, "ok");
          closeModal(); refresh();
        } },
    ],
  });
}

/* ---- EDIT (termasuk ubah URL) ---- */
function doEdit(src) {
  const opt = (v, cur) => `${v}${v === cur ? " selected" : ""}`;
  openModal({
    kind: "info",
    title: `EDIT — ${esc(src.name)}`,
    bodyHtml: `
      <div class="field">
        <label>URL HLS</label>
        <input id="e-url" type="url" value="${esc(src.hls_url)}" />
      </div>
      <div style="background:var(--surface-2); padding:12px; border:1px solid var(--line); margin:12px 0;">
        <p style="margin:0 0 10px 0; font-size:11px; color:var(--muted); letter-spacing:1px;">OPSI LANJUTAN</p>
        <div class="field">
          <label>MODE</label>
          <select id="e-mode">
            <option ${opt("auto", src.mode)}>auto (deteksi codec)</option>
            <option ${opt("copy", src.mode)}>copy (passthrough)</option>
            <option ${opt("transcode", src.mode)}>transcode → H.264</option>
          </select>
        </div>
        <div class="field">
          <label>AUDIO</label>
          <select id="e-audio">
            <option ${opt("aac", src.audio)}>aac</option>
            <option ${opt("copy", src.audio)}>copy</option>
            <option ${opt("drop", src.audio)}>drop (tanpa audio)</option>
          </select>
        </div>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; margin-top:10px;">
          <input type="checkbox" id="e-fast" ${src.fast_start ? "checked" : ""} />
          <span style="font-size:11px; color:var(--text);">FAST START <em style="color:var(--dim); font-style:normal; font-size:10px;">(instant play)</em></span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; margin-top:8px;">
          <input type="checkbox" id="e-lowlat" ${src.low_latency ? "checked" : ""} />
          <span style="font-size:11px; color:var(--text);">LOW LATENCY <em style="color:var(--dim); font-style:normal; font-size:10px;">(live-edge)</em></span>
        </label>
      </div>
    `,
    buttons: [
      { label: "BATAL", cls: "btn-ghost" },
      { label: "SIMPAN", cls: "btn-primary", close: false, onClick: async () => {
          const body = {
            hls_url: $("#e-url").value.trim(),
            mode: $("#e-mode").value,
            audio: $("#e-audio").value,
            fast_start: $("#e-fast").checked,
            low_latency: $("#e-lowlat").checked,
          };
          await action(`/sources/${src.id}`, "PATCH", body);
          toast(`'${src.name}' diperbarui ✔`, "ok");
          closeModal(); refresh();
        } },
    ],
  });
}

async function action(path, method, body) {
  const r = await api(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok && r.status !== 204) {
    const err = await r.json().catch(() => ({}));
    throw new Error(typeof err.detail === "string" ? err.detail : `HTTP ${r.status}`);
  }
}

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
