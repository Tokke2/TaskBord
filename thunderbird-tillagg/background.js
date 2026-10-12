"use strict";

/* ===========================================================================
 * TaskBord — Thunderbird-tillägg (MailExtension, Manifest V3)
 * background.js — hjärnan: menyval, popup-anrop, kö, notiser, retry
 * ===========================================================================
 * Copyright © Rickard Längkvist, 2025–2026
 *
 * Vad tillägget gör
 * -----------------
 * 1. Du markerar ett mail i listan (eller har det öppet) och väljer
 *    "📋 Skicka till TaskBord" (högerklick, verktygsfältets knapp eller
 *    meddelande-knappen).
 * 2. Tillägget skickar MAILET till TaskBords lokala brygga
 *      POST /eml   → rå .eml (originalet sparas i appen, bäst kvalitet)
 *      POST /task  → JSON (reservväg om rå-datat inte kan läsas, t.ex.
 *                    offline-IMAP)
 * 3. TaskBord skapar uppgiften och SPARAR DEN I JSON på disk direkt
 *    (data/active.json) → den finns kvar efter omstart.
 *
 * Om TaskBord inte körs
 * ---------------------
 * Mailet läggs i en kö (storage.local) och skickas automatiskt så snart
 * appen svarar igen (kontrolleras varje minut med alarms). Inget tappas.
 * ===========================================================================
 */

const api = globalThis.messenger ?? globalThis.browser;

const CONFIG_KEY = "config";
const QUEUE_KEY = "taskbord_queue";
const RETRY_ALARM = "taskbord-retry";
const MAX_TRIES = 30;

const DEFAULT_CONFIG = {
  url: "http://127.0.0.1:8765",
  token: "",
  notify: true,       // visa systemnotis när uppgiften skapats
  includeBody: true,  // skicka med brödtexten som anteckning
  includeTags: true,  // Thunderbirds taggar → TaskBords taggar
  useRaw: true        // skicka originalmailet (.eml) när det går
};

/* ---------------------------------------------------------------------------
 * Inställningar (storage.local)
 * ------------------------------------------------------------------------- */

async function loadConfig() {
  let stored = {};
  try {
    const data = await api.storage.local.get(CONFIG_KEY);
    stored = (data && data[CONFIG_KEY]) || {};
  } catch (e) {
    console.warn("[TaskBord] kunde inte läsa inställningar:", e);
  }
  return Object.assign({}, DEFAULT_CONFIG, stored);
}

async function saveConfig(patch) {
  const cfg = Object.assign(await loadConfig(), patch || {});
  cfg.url = normalizeUrl(cfg.url);
  await api.storage.local.set({ [CONFIG_KEY]: cfg });
  return cfg;
}

function normalizeUrl(url) {
  let value = String(url || DEFAULT_CONFIG.url).trim();
  if (!value) value = DEFAULT_CONFIG.url;
  if (!/^https?:\/\//i.test(value)) value = "http://" + value;
  return value.replace(/\/+$/, "");
}

function endpoint(cfg, path) {
  return normalizeUrl(cfg.url) + path;
}

/* ---------------------------------------------------------------------------
 * HTTP mot TaskBord
 * ------------------------------------------------------------------------- */

/**
 * Skicka rå e-postdata (.eml) till bryggan — med ev. extraval i headern.
 */
async function postRaw(cfg, buffer, extraHeaders) {
  const headers = { "Content-Type": "message/rfc822" };
  if (cfg.token) headers["X-TaskBord-Token"] = cfg.token;
  Object.assign(headers, extraHeaders || {});

  let response;
  try {
    response = await fetch(endpoint(cfg, "/eml"), {
      method: "POST",
      headers: headers,
      body: buffer
    });
  } catch (e) {
    const err = new Error("Kunde inte nå TaskBord (" + e.message + ")");
    err.offline = true;
    throw err;
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch (e) {
    payload = {};
  }
  if (!response.ok) {
    const err = new Error(payload.error || ("HTTP " + response.status));
    err.status = response.status;
    throw err;
  }
  return payload;
}

/**
 * Bygg extraval (prioritet/förfallodatum/taggar/titel) som JSON-header.
 * Tom sträng = inget att skicka.
 */
function buildExtras(overrides, payload, cfg) {
  const ov = overrides || {};
  const extra = {};
  if (ov.priority) extra.priority = ov.priority;
  if (ov.due_date) extra.due_date = ov.due_date;
  if (ov.tags && ov.tags.length) extra.tags = ov.tags;
  if (ov.title) extra.title = ov.title;
  if (ov.note) extra.note = ov.note;
  if (!Object.keys(extra).length && payload && payload.tags && cfg.includeTags) {
    extra.tags = payload.tags;   // Thunderbird-taggar → TaskBord-taggar
  }
  return Object.keys(extra).length ? JSON.stringify(extra) : "";
}

async function request(cfg, path, options) {
  const opts = options || {};
  const headers = {};
  if (cfg.token) headers["X-TaskBord-Token"] = cfg.token;
  if (opts.body && opts.contentType) headers["Content-Type"] = opts.contentType;
  Object.assign(headers, opts.headers || {});

  let response;
  try {
    response = await fetch(endpoint(cfg, path), {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body || undefined
    });
  } catch (e) {
    // Nätverksfel = appen körs inte (eller annan port)
    const err = new Error(
      "Kunde inte nå TaskBord på " + normalizeUrl(cfg.url) +
      ". Kör appen? (" + (e && e.message ? e.message : e) + ")"
    );
    err.offline = true;
    throw err;
  }

  let payload = {};
  try {
    payload = await response.json();
  } catch (e) {
    payload = {};
  }

  if (!response.ok) {
    const err = new Error(
      payload.error || ("TaskBord svarade HTTP " + response.status)
    );
    err.status = response.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

/**
 * Testa anslutningen: appen igång? token rätt?
 * Returnerar {ok, level, message} — level: ok | no-app | bad-token
 */
async function testConnection(cfg) {
  const conf = cfg || (await loadConfig());
  let health;
  try {
    health = await request(conf, "/health");
  } catch (e) {
    return {
      ok: false,
      level: "no-app",
      message:
        "❌ Ingen kontakt med TaskBord på " + normalizeUrl(conf.url) +
        ".\n\n• Kör appen? (TaskBord → tray-ikonen ska synas)\n" +
        "• Är e-postbryggan på? Tray-menyn → 📧 E-post & Thunderbird → " +
        "Brygga på/av\n• Rätt port i inställningarna?"
    };
  }
  try {
    await request(conf, "/tasks?limit=1");
  } catch (e) {
    if (e.status === 401) {
      return {
        ok: false,
        level: "bad-token",
        message:
          "⚠️ TaskBord svarar (" + health.app + " " + health.app_version +
          "), men TOKEN stämmer inte.\n\nKopiera inställningarna från " +
          "TaskBord: tray-menyn → 📧 E-post & Thunderbird → " +
          "'Kopiera inställningar för Thunderbird' och klistra in här."
      };
    }
    return { ok: false, level: "no-app", message: "⚠️ " + e.message };
  }
  return {
    ok: true,
    level: "ok",
    message:
      "✅ Ansluten till " + health.app + " " + health.app_version +
      " (brygga " + health.bridge_version + ", " + health.tasks +
      " uppgifter, " + health.imports + " mail importerade)."
  };
}

/* ---------------------------------------------------------------------------
 * Mail → payload
 * ------------------------------------------------------------------------- */

function headerToPayload(header, overrides) {
  const h = header || {};
  const payload = {
    subject: h.subject || "",
    from: h.author || "",
    to: (h.recipients || []).join(", "),
    cc: (h.ccList || []).join(", "),
    date: h.date ? new Date(h.date).toISOString() : new Date().toISOString(),
    message_id: h.headerMessageId || "",
    folder: (h.folder && h.folder.name) || "",
    account: (h.folder && h.folder.accountId) || "",
    source: "thunderbird"
  };
  if (Array.isArray(h.tags) && h.tags.length) {
    payload.tags = h.tags.filter((t) => t && !String(t).startsWith("$"));
  }
  return Object.assign(payload, overrides || {});
}

/** Hämta brödtext (text/plain helst, annars HTML → text). */
async function getPlainTextBody(messageId) {
  try {
    if (api.messages.listInlineTextParts) {
      const parts = await api.messages.listInlineTextParts(messageId);
      const plain = (parts || []).find((p) => p.contentType === "text/plain");
      if (plain && plain.content) return String(plain.content);
      const html = (parts || []).find((p) => p.contentType === "text/html");
      if (html && html.content) {
        if (api.messengerUtilities && api.messengerUtilities.convertToPlainText) {
          try {
            return String(
              await api.messengerUtilities.convertToPlainText(html.content)
            );
          } catch (e) {
            return stripHtml(String(html.content));
          }
        }
        return stripHtml(String(html.content));
      }
    }
    const full = await api.messages.getFull(messageId);
    return findTextInPart(full) || "";
  } catch (e) {
    console.warn("[TaskBord] kunde inte läsa brödtext:", e);
    return "";
  }
}

function findTextInPart(part) {
  if (!part) return "";
  const type = String(part.contentType || "");
  if (type === "text/plain" && typeof part.body === "string") return part.body;
  for (const child of part.parts || []) {
    const found = findTextInPart(child);
    if (found) return found;
  }
  if (type === "text/html" && typeof part.body === "string") {
    return stripHtml(part.body);
  }
  return "";
}

function stripHtml(html) {
  return String(html)
    .replace(/<(style|script)[^>]*>[\s\S]*?<\/\1>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|tr|li|h[1-6])>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/* ---------------------------------------------------------------------------
 * KÖ (mail som inte kunde skickas — skickas när appen svarar igen)
 * ------------------------------------------------------------------------- */

async function loadQueue() {
  try {
    const data = await api.storage.local.get(QUEUE_KEY);
    const q = data && data[QUEUE_KEY];
    return Array.isArray(q) ? q : [];
  } catch (e) {
    return [];
  }
}

async function saveQueue(queue) {
  await api.storage.local.set({ [QUEUE_KEY]: queue });
  await updateBadge(queue.length);
}

async function enqueue(payload, reason) {
  const queue = await loadQueue();
  queue.push({
    payload: payload,
    tries: 0,
    added: Date.now(),
    reason: String(reason || "")
  });
  await saveQueue(queue);
  await ensureRetryAlarm();
  console.info("[TaskBord] mailet köades (" + reason + ") — skickas när appen svarar");
  return queue.length;
}

async function ensureRetryAlarm() {
  try {
    if (!api.alarms) return;
    const existing = await api.alarms.get(RETRY_ALARM);
    if (!existing) {
      await api.alarms.create(RETRY_ALARM, { periodInMinutes: 1 });
      console.info("[TaskBord] retry-timer startad (varje minut)");
    }
  } catch (e) {
    console.warn("[TaskBord] kunde inte starta retry-timer:", e);
  }
}

async function clearRetryAlarm() {
  try {
    if (api.alarms) await api.alarms.clear(RETRY_ALARM);
  } catch (e) {
    /* tyst */
  }
}

async function updateBadge(count) {
  try {
    if (api.action && api.action.setBadgeText) {
      await api.action.setBadgeText({ text: count > 0 ? String(count) : "" });
      if (count > 0 && api.action.setBadgeBackgroundColor) {
        await api.action.setBadgeBackgroundColor({ color: "#f59e0b" });
      }
    }
  } catch (e) {
    /* badge är kosmetiskt — strunta i fel */
  }
}

/** Skicka allt som ligger i kön. Returnerar antal skickade. */
async function flushQueue(silent) {
  const cfg = await loadConfig();
  let queue = await loadQueue();
  if (!queue.length) {
    await clearRetryAlarm();
    return 0;
  }
  const remaining = [];
  let sent = 0;
  for (const item of queue) {
    try {
      const res = await request(cfg, "/task", {
        method: "POST",
        body: JSON.stringify(item.payload),
        contentType: "application/json"
      });
      sent += 1;
      if (!silent) {
        await notifyResult(cfg, res, "kö");
      }
    } catch (e) {
      if (e.offline && item.tries + 1 < MAX_TRIES) {
        item.tries += 1;
        remaining.push(item);
      } else if (e.status === 401) {
        // Fel token — behåll men gnäll inte varje minut
        item.tries += 1;
        remaining.push(item);
        if (!silent) {
          await notify(
            "⚠️ TaskBord: token stämmer inte",
            "Öppna tilläggets inställningar och klistra in inställningarna " +
            "från TaskBord på nytt."
          );
        }
      } else {
        console.error("[TaskBord] kunde inte skicka kö-post:", e);
      }
    }
  }
  await saveQueue(remaining);
  if (!remaining.length) await clearRetryAlarm();
  if (sent) {
    console.info("[TaskBord] " + sent + " köade mail skickades till TaskBord");
  }
  return sent;
}

/* ---------------------------------------------------------------------------
 * Notiser
 * ------------------------------------------------------------------------- */

async function notify(title, message) {
  const cfg = await loadConfig();
  if (!cfg.notify) return;
  try {
    if (api.notifications && api.notifications.create) {
      await api.notifications.create({
        type: "basic",
        title: title,
        message: message,
        iconUrl: "icons/icon-64.png"
      });
      return;
    }
  } catch (e) {
    /* faller igenom till konsolen */
  }
  console.info("[TaskBord] " + title + " — " + message);
}

async function notifyResult(cfg, result, via) {
  const title = result.duplicate
    ? "📋 Redan importerad"
    : "📋 Uppgift skapad i TaskBord";
  const text = result.duplicate
    ? '"' + (result.title || "mailet") + '" finns redan som uppgift.'
    : (result.title || "mailet") +
      (result.saved ? " — sparad i JSON ✔" : "");
  await notify(title, text + (via ? " (" + via + ")" : ""));
}

/* ---------------------------------------------------------------------------
 * HUVUDLOGIK: skicka ett mail som uppgift
 * ------------------------------------------------------------------------- */

/**
 * Skicka ett mail till TaskBord.
 *
 * @param {object} options
 *   messageId   {number}  Thunderbird-internt id
 *   header      {object}  MessageHeader (om vi redan har den)
 *   overrides   {object}  t.ex. {priority, due_date, tags, title, note}
 *   tabId       {number}  för popup-kontext (visat meddelande)
 * @returns {object} {ok, duplicate, task_id, title, transport, queued}
 */
async function sendMessageAsTask(options) {
  const opts = options || {};
  const cfg = await loadConfig();

  if (!cfg.token) {
    return {
      ok: false,
      error:
        "Ingen token inställd. Öppna tilläggets inställningar och klistra " +
        "in inställningarna från TaskBord (tray-menyn → 📧 E-post & " +
        "Thunderbird → Kopiera inställningar för Thunderbird)."
    };
  }

  let header = opts.header || null;
  if (!header && opts.messageId) {
    try {
      header = await api.messages.get(opts.messageId);
    } catch (e) {
      console.warn("[TaskBord] kunde inte läsa meddelandet:", e);
    }
  }

  let payload = headerToPayload(header, opts.overrides);
  if (!payload.subject && !payload.title) {
    payload.title = "Uppgift från Thunderbird";
  }
  if (!cfg.includeTags) delete payload.tags;

  // 1. Försök skicka ORIGINALMAILET (.eml) — då sparas originalet i appen
  if (opts.messageId && cfg.useRaw) {
    try {
      const raw = await api.messages.getRaw(opts.messageId, {
        data_format: "File"
      });
      if (raw && typeof raw.arrayBuffer === "function") {
        const buffer = await raw.arrayBuffer();
        // Användarens val (prioritet/datum/taggar) följer med som
        // X-TaskBord-Extra — INGET extra /task-anrop (det gav förr i
        // tiden en DUBBEL uppgift, hittat i E2E-test v7-fix90b).
        const extra = buildExtras(opts.overrides, payload, cfg);
        const headers = extra ? { "X-TaskBord-Extra": extra } : {};
        const res = await postRaw(cfg, buffer, headers);
        await notifyResult(cfg, res, "original");
        return Object.assign({ transport: "eml", queued: false }, res);
      }
    } catch (e) {
      if (e.status === 401) {
        return { ok: false, error: e.message };
      }
      if (e.offline) {
        // Appen är inte igång → köa JSON-varianten (den kan skickas senare
        // även om Thunderbirds id-nummer ändrats efter omstart)
        if (cfg.includeBody && opts.messageId) {
          const body = await getPlainTextBody(opts.messageId);
          if (body) payload.note = body;
        }
        const len = await enqueue(payload, "TaskBord körs inte");
        await notify(
          "📥 TaskBord körs inte — mailet köat",
          "Uppgiften skapas automatiskt när TaskBord startar (" +
          len + " i kön)."
        );
        return { ok: true, queued: true, transport: "queue" };
      }
      console.warn(
        "[TaskBord] kunde inte skicka originalmail, provar JSON-vägen:", e
      );
    }
  }

  // 2. Reservväg: JSON-payload
  if (cfg.includeBody && opts.messageId && !payload.note) {
    const body = await getPlainTextBody(opts.messageId);
    if (body) payload.note = body;
  }

  try {
    const res = await request(cfg, "/task", {
      method: "POST",
      body: JSON.stringify(payload),
      contentType: "application/json"
    });
    await notifyResult(cfg, res, "json");
    return Object.assign({ transport: "json", queued: false }, res);
  } catch (e) {
    if (e.offline) {
      const len = await enqueue(payload, "TaskBord körs inte");
      await notify(
        "📥 TaskBord körs inte — mailet köat",
        "Uppgiften skapas automatiskt när TaskBord startar (" + len + " i kön)."
      );
      return { ok: true, queued: true, transport: "queue" };
    }
    return { ok: false, error: e.message };
  }
}

/** Skicka en helt egen uppgift (popupens "snabbuppgift"). */
async function sendQuickTask(data) {
  const cfg = await loadConfig();
  if (!cfg.token) {
    return {
      ok: false,
      error:
        "Ingen token inställd. Öppna inställningarna och klistra in " +
        "inställningarna från TaskBord."
    };
  }
  const payload = {
    title: String((data && data.title) || "").trim(),
    note: String((data && data.note) || "").trim(),
    priority: (data && data.priority) || undefined,
    due_date: (data && data.due_date) || undefined,
    tags: (data && data.tags) || undefined,
    source: "thunderbird-popup"
  };
  if (!payload.title) return { ok: false, error: "Uppgiften saknar titel" };
  try {
    const res = await request(cfg, "/task", {
      method: "POST",
      body: JSON.stringify(payload),
      contentType: "application/json"
    });
    await notifyResult(cfg, res, "json");
    return Object.assign({ transport: "json" }, res);
  } catch (e) {
    if (e.offline) {
      const len = await enqueue(payload, "TaskBord körs inte");
      return { ok: true, queued: true, queued_count: len };
    }
    return { ok: false, error: e.message };
  }
}

/* ---------------------------------------------------------------------------
 * Menyer
 * ------------------------------------------------------------------------- */

function buildMenus() {
  const items = [
    {
      id: "taskbord-send",
      title: "📋 Skicka till TaskBord (ny uppgift)",
      contexts: ["message_list"]
    },
    {
      id: "taskbord-send-display",
      title: "📋 Skicka till TaskBord (ny uppgift)",
      contexts: ["message_display_action"]
    },
    {
      id: "taskbord-options",
      title: "⚙️ TaskBord-inställningar…",
      contexts: ["tools_menu", "message_list", "message_display_action"]
    }
  ];
  for (const item of items) {
    try {
      api.menus.create(item);
    } catch (e) {
      console.warn("[TaskBord] menus.create misslyckades:", item.id, e);
    }
  }
}

api.menus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === "taskbord-options") {
      await api.runtime.openOptionsPage();
      return;
    }

    let messageId = null;
    let header = null;

    if (info.selectedMessages && info.selectedMessages.messages) {
      const first = info.selectedMessages.messages[0];
      if (first) {
        messageId = first.id;
        header = first;
      }
    }

    if (!messageId && tab) {
      header = await getDisplayedHeader(tab.id);
      if (header) messageId = header.id;
    }

    if (!messageId) {
      await notify("📋 TaskBord", "Hitta inget mail — markera ett mail först.");
      return;
    }
    const res = await sendMessageAsTask({ messageId, header });
    if (!res.ok) {
      await notify("⚠️ TaskBord", res.error || "Kunde inte skapa uppgiften.");
    }
  } catch (e) {
    console.error("[TaskBord] meny-klick misslyckades:", e);
    await notify("⚠️ TaskBord", String(e && e.message ? e.message : e));
  }
});

/** Hämta MessageHeader för meddelandet som visas i en flik. */
async function getDisplayedHeader(tabId) {
  try {
    if (api.messageDisplay.getDisplayedMessages) {
      const list = await api.messageDisplay.getDisplayedMessages(tabId);
      const first = list && list.messages && list.messages[0];
      if (first) return first;
    }
    if (api.messageDisplay.getDisplayedMessage) {
      return await api.messageDisplay.getDisplayedMessage(tabId);
    }
  } catch (e) {
    console.warn("[TaskBord] kunde inte läsa visat meddelande:", e);
  }
  return null;
}

/* ---------------------------------------------------------------------------
 * Popup ↔ bakgrund
 * ------------------------------------------------------------------------- */

api.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      const type = message && message.type;
      if (type === "send-displayed") {
        const header = await getDisplayedHeader(message.tabId);
        if (!header) {
          sendResponse({ ok: false, error: "Inget mail visas just nu." });
          return;
        }
        sendResponse(
          await sendMessageAsTask({
            messageId: header.id,
            header: header,
            overrides: message.overrides || {}
          })
        );
        return;
      }
      if (type === "send-quick") {
        sendResponse(await sendQuickTask(message.data || {}));
        return;
      }
      if (type === "get-config") {
        sendResponse({ ok: true, config: await loadConfig() });
        return;
      }
      if (type === "save-config") {
        sendResponse({ ok: true, config: await saveConfig(message.config || {}) });
        return;
      }
      if (type === "test-connection") {
        const cfg = message.config
          ? Object.assign(await loadConfig(), message.config)
          : null;
        sendResponse(await testConnection(cfg));
        return;
      }
      if (type === "flush-queue") {
        sendResponse({ ok: true, sent: await flushQueue(false) });
        return;
      }
      if (type === "queue-status") {
        const queue = await loadQueue();
        sendResponse({ ok: true, count: queue.length });
        return;
      }
      sendResponse({ ok: false, error: "Okänt meddelande: " + type });
    } catch (e) {
      sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
    }
  })();
  return true; // asynkront svar
});

/* ---------------------------------------------------------------------------
 * Start + retry-timer
 * ------------------------------------------------------------------------- */

async function startup() {
  console.info("[TaskBord] tillägg startat " + (api.runtime.getManifest().version));
  buildMenus();
  await updateBadge((await loadQueue()).length);
  // Skicka eventuella köade mail (appen kanske är igång nu)
  await flushQueue(true);
  if ((await loadQueue()).length) await ensureRetryAlarm();
}

try {
  api.runtime.onStartup.addListener(() => {
    startup().catch((e) => console.warn("[TaskBord] startup:", e));
  });
} catch (e) {
  /* vissa versioner saknar onStartup — då räcker onInstalled/top-level */
}

try {
  api.runtime.onInstalled.addListener((details) => {
    console.info("[TaskBord] installerad/uppdaterad:", details.reason);
    startup().catch((e) => console.warn("[TaskBord] onInstalled:", e));
    if (details.reason === "install" && api.runtime.openOptionsPage) {
      // Första gången: öppna inställningarna så att token kan klistras in
      api.runtime.openOptionsPage();
    }
  });
} catch (e) {
  /* tyst */
}

if (api.alarms && api.alarms.onAlarm) {
  api.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === RETRY_ALARM) {
      flushQueue(false).catch((e) => console.warn("[TaskBord] retry:", e));
    }
  });
}

startup().catch((e) => console.warn("[TaskBord] startup (top-level):", e));
