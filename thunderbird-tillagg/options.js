"use strict";

/* TaskBord — options.js
 * Inställningar: adress + token (klistra in från TaskBord), anslutningstest.
 */

const api = globalThis.messenger ?? globalThis.browser;

const el = (id) => document.getElementById(id);

function setStatus(text, kind) {
  const box = el("status");
  box.className = kind || "";
  box.textContent = text || "";
}

function readForm() {
  return {
    url: el("url").value.trim(),
    token: el("token").value.trim(),
    useRaw: el("useRaw").checked,
    includeBody: el("includeBody").checked,
    includeTags: el("includeTags").checked,
    notify: el("notify").checked
  };
}

function fillForm(cfg) {
  el("url").value = cfg.url || "";
  el("token").value = cfg.token || "";
  el("useRaw").checked = cfg.useRaw !== false;
  el("includeBody").checked = cfg.includeBody !== false;
  el("includeTags").checked = cfg.includeTags !== false;
  el("notify").checked = cfg.notify !== false;
}

async function send(message) {
  return await api.runtime.sendMessage(message);
}

/* --- Läs in JSON som kopierats från TaskBord --------------------------- */

function parsePasted(text) {
  const raw = String(text || "").trim();
  if (!raw) return null;
  // 1. Ren JSON
  try {
    const data = JSON.parse(raw);
    if (data && typeof data === "object") return data;
  } catch (e) {
    /* prova att plocka ut fälten nedan */
  }
  // 2. Tålmodig tolkning: "url": "...", "token": "..." (vilken ordning som helst)
  const url = raw.match(/https?:\/\/[^\s"'<>]+/i);
  const token = raw.match(/["']?token["']?\s*[:=]\s*["']?([A-Za-z0-9._\-]{8,128})/i);
  if (url || token) {
    return {
      url: url ? url[0] : undefined,
      token: token ? token[1] : undefined
    };
  }
  return null;
}

el("applyPaste").addEventListener("click", async () => {
  const data = parsePasted(el("paste").value);
  if (!data) {
    setStatus(
      "⚠️ Kunde inte tolka texten. Klistra in hela JSON-raden från TaskBord.",
      "warn"
    );
    return;
  }
  const patch = {};
  if (data.url) patch.url = data.url;
  if (data.token) patch.token = data.token;
  if (!Object.keys(patch).length) {
    setStatus("⚠️ Hittade ingen adress/token i texten.", "warn");
    return;
  }
  const res = await send({ type: "save-config", config: patch });
  if (res && res.ok) {
    fillForm(res.config);
    setStatus("✅ Inställningarna sparade. Testar anslutningen…", "ok");
    await doTest();
  } else {
    setStatus("⚠️ Kunde inte spara.", "err");
  }
});

el("pasteUrlOnly").addEventListener("click", async () => {
  const data = parsePasted(el("paste").value);
  if (!data || !data.url) {
    setStatus("⚠️ Hittade ingen adress.", "warn");
    return;
  }
  const res = await send({ type: "save-config", config: { url: data.url } });
  fillForm(res.config);
  setStatus("✅ Adress sparad: " + res.config.url, "ok");
});

/* --- Test / sparande --------------------------------------------------- */

async function doTest() {
  const form = readForm();
  setStatus("Testar anslutning mot " + form.url + " …");
  const res = await send({ type: "test-connection", config: form });
  if (res && res.ok) {
    if (el("token").value.trim()) {
      await send({ type: "save-config", config: form });
    }
    setStatus(res.message, "ok");
  } else {
    setStatus(
      (res && res.message) || "⚠️ Ingen kontakt med TaskBord.",
      res && res.level === "bad-token" ? "warn" : "err"
    );
  }
}

el("test").addEventListener("click", doTest);

el("save").addEventListener("click", async () => {
  const res = await send({ type: "save-config", config: readForm() });
  if (res && res.ok) {
    fillForm(res.config);
    setStatus("✅ Sparat: " + res.config.url, "ok");
  } else {
    setStatus("⚠️ Kunde inte spara inställningarna.", "err");
  }
});

/* --- Start ------------------------------------------------------------- */

(async function init() {
  const res = await send({ type: "get-config" });
  if (res && res.ok) fillForm(res.config);
  await doTest();
})();
