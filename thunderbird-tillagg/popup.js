"use strict";

/* TaskBord — popup.js
 * Visar det mail som är öppet/markerat och skickar det till TaskBord.
 * Kan även skapa en helt fristående uppgift.
 */

const api = globalThis.messenger ?? globalThis.browser;

const el = (id) => document.getElementById(id);
let currentTabId = null;
let currentHeader = null;

function setStatus(text, kind) {
  const box = el("status");
  box.className = kind || "";
  box.textContent = text || "";
}

function overrides() {
  const o = {};
  const prio = el("priority").value;
  if (prio) o.priority = prio;
  const due = el("due").value.trim();
  if (due) o.due_date = due;
  const tags = el("tags").value.trim();
  if (tags) o.tags = tags.split(/[,;]/).map((t) => t.trim()).filter(Boolean);
  return o;
}

async function send(message) {
  return await api.runtime.sendMessage(message);
}

/* --- 1. Hitta visat meddelande ----------------------------------------- */

async function findDisplayedMessage() {
  try {
    const tabs = await api.tabs.query({ active: true, currentWindow: true });
    if (!tabs || !tabs.length) return null;
    currentTabId = tabs[0].id;
    if (api.messageDisplay.getDisplayedMessages) {
      const list = await api.messageDisplay.getDisplayedMessages(currentTabId);
      const first = list && list.messages && list.messages[0];
      if (first) return first;
    }
    if (api.messageDisplay.getDisplayedMessage) {
      return await api.messageDisplay.getDisplayedMessage(currentTabId);
    }
  } catch (e) {
    console.warn("[TaskBord] popup: kunde inte läsa visat mail:", e);
  }
  return null;
}

/* --- 2. Anslutningsstatus ---------------------------------------------- */

async function checkService() {
  const dot = el("dot");
  const text = el("serviceText");
  dot.textContent = "⚪";
  text.textContent = "Kontrollerar TaskBord…";
  const res = await send({ type: "test-connection" });
  if (res && res.ok) {
    dot.textContent = "🟢";
    text.textContent = res.message.replace(/^✅\s*/, "");
  } else {
    dot.textContent = res && res.level === "bad-token" ? "🟡" : "🔴";
    text.textContent =
      res && res.level === "bad-token"
        ? "TaskBord körs — men token stämmer inte (⚙️)"
        : "Ingen kontakt med TaskBord (⚙️ för inställningar)";
  }
  await refreshQueue();
}

async function refreshQueue() {
  const res = await send({ type: "queue-status" });
  const box = el("queue");
  if (res && res.count > 0) {
    box.textContent =
      "📥 " + res.count + " köat/ade mail — skickas när TaskBord svarar.";
    const sent = await send({ type: "flush-queue" });
    if (sent && sent.sent > 0) {
      await refreshQueue();
    }
  } else {
    box.textContent = "";
  }
}

/* --- 3. Händelser ------------------------------------------------------ */

el("sendMail").addEventListener("click", async () => {
  el("sendMail").disabled = true;
  setStatus("Skickar mailet till TaskBord…");
  try {
    const res = await send({
      type: "send-displayed",
      tabId: currentTabId,
      overrides: overrides()
    });
    handleResult(res);
  } catch (e) {
    setStatus("Fel: " + (e && e.message ? e.message : e), "err");
  } finally {
    el("sendMail").disabled = false;
    await refreshQueue();
  }
});

el("sendQuick").addEventListener("click", async () => {
  const title = el("quickTitle").value.trim();
  if (!title) {
    setStatus("Skriv en uppgiftstext först.", "warn");
    return;
  }
  setStatus("Skapar uppgift…");
  try {
    const res = await send({
      type: "send-quick",
      data: {
        title: title,
        note: el("quickNote").value.trim(),
        priority: el("priority").value || undefined,
        due_date: el("due").value.trim() || undefined,
        tags: el("tags").value.trim() || undefined
      }
    });
    handleResult(res, true);
  } catch (e) {
    setStatus("Fel: " + (e && e.message ? e.message : e), "err");
  } finally {
    await refreshQueue();
  }
});

function handleResult(res, quick) {
  if (!res) {
    setStatus("Inget svar från bakgrundsskriptet.", "err");
    return;
  }
  if (res.queued) {
    setStatus(
      "📥 TaskBord körs inte just nu — mailet ligger i kön och skickas " +
      "automatiskt när appen startar.",
      "warn"
    );
    return;
  }
  if (!res.ok) {
    setStatus("⚠️ " + (res.error || "Kunde inte skapa uppgiften."), "err");
    return;
  }
  if (res.duplicate) {
    setStatus("ℹ️ Mailet är redan importerat (uppgiften finns i appen).", "warn");
    return;
  }
  setStatus("✅ Uppgift skapad: " + (res.title || "klart"), "ok");
  if (quick) {
    el("quickTitle").value = "";
    el("quickNote").value = "";
  }
  checkService();
}

el("openOptions").addEventListener("click", () => {
  api.runtime.openOptionsPage();
});

/* --- 4. Start --------------------------------------------------------- */

(async function init() {
  currentHeader = await findDisplayedMessage();
  if (currentHeader) {
    const info = el("mailInfo");
    info.className = "";
    const subject = document.createElement("div");
    subject.className = "mail-subject";
    subject.textContent = currentHeader.subject || "(inget ämne)";
    const from = document.createElement("div");
    from.className = "mail-from";
    from.textContent = currentHeader.author || "";
    info.replaceChildren(subject, from);
    el("sendMail").disabled = false;
    if (Array.isArray(currentHeader.tags) && currentHeader.tags.length) {
      el("tags").value = currentHeader.tags
        .filter((t) => t && !String(t).startsWith("$"))
        .join(", ");
    }
  } else {
    el("mailInfo").textContent =
      "Inget mail markerat/öppet — använd fältet nedan för en ny uppgift.";
  }
  await checkService();
})();
