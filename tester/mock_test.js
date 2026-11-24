/* ===========================================================================
 * mock_test.js — E2E-test av Ledgebord-tillägget UTAN Thunderbird.
 *
 * Kör:  node tester/mock_test.js [url] [token]
 *
 * Testet härmar Thunderbirds WebExtension-API (messenger.*), laddar den
 * RIKTIGA background.js och pratar med en RIKTIG Ledgebord-brygga (Python).
 * Verifierar: meny-klick, popup, snabbuppgift, offline-kö, dublett, token.
 * ===========================================================================
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const BASE = process.argv[2] || "http://127.0.0.1:8770";
const TOKEN = process.argv[3] || "e2etoken1234567890";
const ADDON_DIR = path.resolve(__dirname, "..", "thunderbird-tillagg");

let failures = 0;
function ok(name, cond, extra) {
  const mark = cond ? "  ✓" : "  ✗";
  if (!cond) failures += 1;
  console.log(mark + " " + name + (extra && !cond ? "  → " + extra : ""));
}

/* --- 1. Mock av Thunderbird-API:t -------------------------------------- */

const storage = {};
const listeners = { menus: [], message: [], alarm: [], startup: [], installed: [] };
const notifications = [];
const badge = { text: "" };
let fetchCalls = [];

const MESSAGES = [
  {
    id: 101,
    subject: "Faktura 2026-10 måste betalas",
    author: "Leverantör AB <faktura@lev.example>",
    recipients: ["rickard@example.com"],
    ccList: [],
    date: new Date("2026-10-12T07:30:00+02:00"),
    headerMessageId: "<e2e-faktura-1@example.com>",
    folder: { name: "Inkorgen", accountId: "acc1" },
    tags: ["jobb", "$label1"]
  },
  {
    id: 102,
    subject: "Lunch på fredag?",
    author: "Anna <anna@example.com>",
    recipients: ["rickard@example.com"],
    ccList: [],
    date: new Date("2026-10-12T09:15:00+02:00"),
    headerMessageId: "<e2e-lunch-2@example.com>",
    folder: { name: "Inkorgen", accountId: "acc1" },
    tags: []
  },
  {
    id: 103,
    subject: "Offert till kund A",
    author: "Bosse <bosse@example.com>",
    recipients: ["rickard@example.com"],
    ccList: [],
    date: new Date("2026-10-13T08:00:00+02:00"),
    headerMessageId: "<e2e-offert-3@example.com>",
    folder: { name: "Inkorgen", accountId: "acc1" },
    tags: []
  },
  {
    id: 104,
    subject: "Boka möte med revisorn",
    author: "Cissi <cissi@example.com>",
    recipients: ["rickard@example.com"],
    ccList: [],
    date: new Date("2026-10-13T08:30:00+02:00"),
    headerMessageId: "<e2e-mote-4@example.com>",
    folder: { name: "Inkorgen", accountId: "acc1" },
    tags: []
  }
];

function rawEml(msg) {
  return Buffer.from(
    `From: ${msg.author}\r\n` +
    `To: ${msg.recipients.join(", ")}\r\n` +
    `Subject: ${msg.subject}\r\n` +
    `Message-ID: ${msg.headerMessageId}\r\n` +
    `Date: ${msg.date.toUTCString()}\r\n` +
    `Content-Type: text/plain; charset=utf-8\r\n` +
    `\r\n` +
    `Hej! Detta är brödtexten till "${msg.subject}".\r\nMvh\r\n`,
    "utf-8"
  );
}

const messenger = {
  runtime: {
    getManifest: () => ({ version: "1.0.0" }),
    openOptionsPage: async () => {},
    onMessage: { addListener: (fn) => listeners.message.push(fn) },
    onStartup: { addListener: (fn) => listeners.startup.push(fn) },
    onInstalled: { addListener: (fn) => listeners.installed.push(fn) }
  },
  storage: {
    local: {
      get: async (key) => {
        const k = typeof key === "string" ? key : (key && key[0]);
        return k in storage ? { [k]: storage[k] } : {};
      },
      set: async (obj) => Object.assign(storage, obj)
    }
  },
  menus: {
    create: () => {},
    onClicked: { addListener: (fn) => listeners.menus.push(fn) }
  },
  alarms: {
    get: async () => null,
    create: async () => {},
    clear: async () => {},
    onAlarm: { addListener: (fn) => listeners.alarm.push(fn) }
  },
  notifications: {
    create: async (opts) => {
      notifications.push(opts);
      return "id";
    }
  },
  action: {
    setBadgeText: async (d) => {
      badge.text = d.text;
    },
    setBadgeBackgroundColor: async () => {}
  },
  messages: {
    get: async (id) => MESSAGES.find((m) => m.id === id),
    getRaw: async (id) => {
      const msg = MESSAGES.find((m) => m.id === id);
      const buf = rawEml(msg);
      return {
        size: buf.length,
        arrayBuffer: async () =>
          buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
      };
    },
    listInlineTextParts: async (id) => {
      const msg = MESSAGES.find((m) => m.id === id);
      return [{ contentType: "text/plain", content: "Brödtext för " + msg.subject }];
    }
  },
  messageDisplay: {
    getDisplayedMessages: async (tabId) => ({ messages: [MESSAGES[0]] }),
    getDisplayedMessage: async () => MESSAGES[0]
  },
  tabs: { query: async () => [{ id: 7 }] },
  messengerUtilities: {
    convertToPlainText: async (html) => html
  }
};

/* --- 2. Ladda den RIKTIGA background.js i en sandbox ------------------- */

const sandbox = {
  console,
  fetch,
  setTimeout,
  clearTimeout,
  Promise,
  Date,
  JSON,
  Object,
  Array,
  String,
  Number,
  Math,
  Error,
  URL,
  Buffer,
  messenger,
  browser: messenger,
  globalThis: undefined
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const code = fs.readFileSync(path.join(ADDON_DIR, "background.js"), "utf-8");
vm.runInContext(code, sandbox, { filename: "background.js" });

function callBackground(message) {
  return new Promise((resolve, reject) => {
    const fn = listeners.message[0];
    if (!fn) return reject(new Error("ingen onMessage-lyssnare"));
    const timer = setTimeout(() => reject(new Error("timeout")), 15000);
    fn(message, {}, (res) => {
      clearTimeout(timer);
      resolve(res);
    });
  });
}

function clickMenu(info, tab) {
  const fn = listeners.menus[0];
  if (!fn) throw new Error("ingen meny-lyssnare");
  return fn(info, tab);
}

async function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function getTasks() {
  const res = await fetch(BASE + "/tasks?limit=200", {
    headers: { "X-TaskBord-Token": TOKEN }
  });
  return (await res.json()).tasks;
}

/* --- 3. Testerna ------------------------------------------------------- */

(async function main() {
  console.log("=".repeat(66));
  console.log("E2E-test: Ledgebord-tillägget (mockad Thunderbird) → " + BASE);
  console.log("=".repeat(66));
  await wait(300);

  // 1. Konfigurera tillägget
  let res = await callBackground({
    type: "save-config",
    config: { url: BASE, token: TOKEN, useRaw: true, includeBody: true,
              includeTags: true, notify: true }
  });
  ok("spara inställningar (url + token)", res.ok && res.config.token === TOKEN,
     JSON.stringify(res));

  // 2. Testa anslutning
  res = await callBackground({ type: "test-connection" });
  ok("testa anslutning mot bryggan", res.ok, res.message);
  console.log("      " + (res.message || "").split("\n")[0]);

  // 3. Meny-klick: högerklicka på mail i listan
  await clickMenu(
    { menuItemId: "taskbord-send",
      selectedMessages: { messages: [MESSAGES[0]] } },
    { id: 7 }
  );
  await wait(600);
  let tasks = await getTasks();
  ok("meny-klick skapade uppgift", tasks.length === 1,
     JSON.stringify(tasks.map((t) => t.title)));
  ok("titeln kommer från mailämnet",
     tasks[0] && tasks[0].title === "Faktura 2026-10 måste betalas",
     tasks[0] && tasks[0].title);
  ok("Thunderbird-tagg → Ledgebord-tagg (system-taggar bort)",
     tasks[0] && tasks[0].tags.includes("jobb") &&
     !tasks[0].tags.some((t) => t.startsWith("$")),
     JSON.stringify(tasks[0] && tasks[0].tags));

  const activeJson = JSON.parse(
    fs.readFileSync("/tmp/bridge_e2e/data/active.json", "utf-8")
  );
  ok("uppgiften ligger i data/active.json (kvar efter omstart)",
     activeJson.tasks.some((t) => t.title === "Faktura 2026-10 måste betalas"),
     JSON.stringify(activeJson.tasks.map((t) => t.title)));
  ok("originalmail (.eml) sparades i data/emails/",
     fs.readdirSync("/tmp/bridge_e2e/data/emails")
       .filter((f) => f.endsWith(".eml")).length >= 1,
     fs.readdirSync("/tmp/bridge_e2e/data/emails").join(","));

  // 4. DUBLETT: skicka samma mail igen
  await clickMenu(
    { menuItemId: "taskbord-send",
      selectedMessages: { messages: [MESSAGES[0]] } },
    { id: 7 }
  );
  await wait(600);
  tasks = await getTasks();
  ok("samma mail igen → ingen ny uppgift (dedup)", tasks.length === 1,
     "antal=" + tasks.length + " " + JSON.stringify(tasks.map((t) => t.title)));

  // 5. Popup: skicka SAMMA mail med prioritet + förfallodatum.
  //    Extras ska appliceras på den befintliga uppgiften (ingen dubblett).
  res = await callBackground({
    type: "send-displayed",
    tabId: 7,
    overrides: { priority: "high", due_date: "imorgon" }
  });
  await wait(500);
  ok("popup 'Skicka mailet som uppgift' fungerar", res && res.ok && res.duplicate,
     JSON.stringify(res));
  tasks = await getTasks();
  ok("popup-val (prioritet/datum) applicerades — ingen dubbel uppgift",
     tasks.length === 1 && tasks[0].priority === "high" && !!tasks[0].due_date,
     tasks.length + " uppgifter: " +
     JSON.stringify(tasks.map((t) => [t.title, t.priority, t.due_date])));

  // 6. Snabbuppgift från popupen (ingen e-post)
  res = await callBackground({
    type: "send-quick",
    data: { title: "Ring Anna klockan 14", note: "Från popupen",
            priority: "low", due_date: "2026-10-20", tags: "telefon" }
  });
  await wait(500);
  ok("snabbuppgift skapas", res && res.ok && !res.duplicate, JSON.stringify(res));

  tasks = await getTasks();
  const titles = tasks.map((t) => t.title);
  ok("2 uppgifter i Ledgebord nu (mail + snabbuppgift)", tasks.length === 2,
     JSON.stringify(titles));
  const ring = tasks.find((t) => t.title === "Ring Anna klockan 14");
  ok("snabbuppgiftens prioritet/datum/tagg sparades",
     ring && ring.priority === "low" && ring.due_date === "2026-10-20" &&
     ring.tags.includes("telefon"),
     JSON.stringify(ring));

  // 7. Notiser visades (tray/system)
  ok("systemnotis skickades", notifications.length >= 3,
     "antal=" + notifications.length);

  // 8. Rätt token krävs (fel token → felhantering, inte tyst)
  await callBackground({
    type: "save-config", config: { url: BASE, token: "fel-token" }
  });
  res = await callBackground({
    type: "send-quick", data: { title: "Ska misslyckas" }
  });
  ok("fel token ger tydligt fel (ingen tystnad)",
     res && !res.ok && /token/i.test(res.error || ""), JSON.stringify(res));

  // 9. OFFLINE: Ledgebord körs inte → kön tar över
  await callBackground({
    type: "save-config",
    config: { url: "http://127.0.0.1:9", token: TOKEN }
  });
  res = await callBackground({
    type: "send-quick", data: { title: "Köat offline-mail" }
  });
  ok("offline → mailet köas (inget tappas)", res && res.queued === true,
     JSON.stringify(res));
  let q = await callBackground({ type: "queue-status" });
  ok("kön innehåller posten", q.count === 1, "count=" + q.count);

  // 10. Appen "startar" igen → kön skickas automatiskt
  await callBackground({
    type: "save-config", config: { url: BASE, token: TOKEN }
  });
  const sent = await callBackground({ type: "flush-queue" });
  ok("kön skickades när bryggan svarade igen", sent.sent === 1,
     JSON.stringify(sent));
  await wait(400);
  q = await callBackground({ type: "queue-status" });
  ok("kön är tom efter leverans", q.count === 0, "count=" + q.count);
  tasks = await getTasks();
  ok("det köade mailet blev en uppgift",
     tasks.some((t) => t.title === "Köat offline-mail"),
     JSON.stringify(tasks.map((t) => t.title)));
  ok("3 uppgifter totalt (inkl. köade mailet)", tasks.length === 3,
     JSON.stringify(tasks.map((t) => t.title)));

  // 11. FLERA MAIL PÅ EN GÅNG: markera 3 (varav ett redan importerat) → 2 nya uppgifter
  //     och EN sammanfattande notis
  const notesBefore = notifications.length;
  await clickMenu(
    { menuItemId: "taskbord-send",
      selectedMessages: { messages: [MESSAGES[2], MESSAGES[3], MESSAGES[0]] } },
    { id: 7 }
  );
  await wait(900);
  tasks = await getTasks();
  const bt = tasks.map((t) => t.title);
  ok("flera mail: båda nya mailen blev uppgifter",
     bt.includes("Offert till kund A") && bt.includes("Boka möte med revisorn"),
     JSON.stringify(bt));
  ok("flera mail: redan importerat mail dubblerades inte",
     bt.filter((t) => t === "Faktura 2026-10 måste betalas").length === 1,
     JSON.stringify(bt));
  ok("flera mail: 5 uppgifter totalt", tasks.length === 5, "antal=" + tasks.length);
  const newNotes = notifications.slice(notesBefore);
  ok("flera mail: EN sammanfattande notis (inte tre)", newNotes.length === 1,
     JSON.stringify(newNotes.map((n) => n.title + ": " + n.message)));
  ok("flera mail: notisen anger 2 skapade och 1 som fanns redan",
     newNotes[0] && /2 uppgifter skapade/.test(newNotes[0].message) &&
     /1 fanns redan/.test(newNotes[0].message),
     newNotes[0] && newNotes[0].message);
  const emlTexts = fs
    .readdirSync("/tmp/bridge_e2e/data/emails")
    .filter((f) => f.endsWith(".eml"))
    .map((f) => fs.readFileSync("/tmp/bridge_e2e/data/emails/" + f, "utf8"));
  ok("flera mail: originalmailen sparades för båda nya (för 'Öppna mejlet')",
     emlTexts.some((t) => t.includes("Offert till kund A")) &&
     emlTexts.some((t) => t.includes("Boka möte med revisorn")),
     "antal eml=" + emlTexts.length);

  // 12. Ett enda markerat mail beter sig som förut (egen notis)
  const before1 = notifications.length;
  await clickMenu(
    { menuItemId: "taskbord-send", selectedMessages: { messages: [MESSAGES[1]] } },
    { id: 7 }
  );
  await wait(500);
  ok("ett mail: vanlig notis som förut", notifications.length === before1 + 1 &&
     /Lunch på fredag/.test(notifications[notifications.length - 1].message),
     JSON.stringify(notifications.slice(before1)));

  // 13. Flera mail när Ledgebord inte körs → alla köas, en notis
  await callBackground({ type: "save-config", config: { url: "http://127.0.0.1:9", token: TOKEN } });
  const before2 = notifications.length;
  await clickMenu(
    { menuItemId: "taskbord-send", selectedMessages: { messages: [MESSAGES[2], MESSAGES[3]] } },
    { id: 7 }
  );
  await wait(500);
  q = await callBackground({ type: "queue-status" });
  ok("flera mail offline: båda köade", q.count === 2, "count=" + q.count);
  ok("flera mail offline: en notis som säger att de köats",
     notifications.length === before2 + 1 && /2 köade/.test(notifications[notifications.length - 1].message),
     JSON.stringify(notifications.slice(before2)));

  console.log("=".repeat(66));
  if (failures) {
    console.log("✗ " + failures + " TEST(ER) MISSLYCKADES");
    process.exit(1);
  }
  console.log("✓ ALLA E2E-TESTER PASSERADE (" + tasks.length +
              " uppgifter i Ledgebord, " + notifications.length + " notiser)");
  console.log("=".repeat(66));
  process.exit(0);
})().catch((e) => {
  console.error("✗ Testet kraschade:", e);
  process.exit(1);
});
