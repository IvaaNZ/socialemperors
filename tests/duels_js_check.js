// Runs templates/js/duels.js in Node with a small fake DOM and feeds it every
// server message type; prints a JSON report. Used by tests/test_duels_js.py.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "..", "templates", "js", "duels.js"), "utf8");
// "game" (play page), "aside" (a second game tab), "portal", "portal-game-open" (a portal page while a game tab
// of this browser is open) or "claimed" (a game tab whose battle another game tab already claimed)
const mode = process.argv[2] || "game";
// Every text key the server sends (duels_web.duel_texts), as "[key]" plus the placeholders.
const webSource = fs.readFileSync(path.join(__dirname, "..", "duels_web.py"), "utf8");
const texts = {};
for (const match of webSource.matchAll(/'(\w+)': _\(/g)) texts[match[1]] = `[${match[1]}]{name}{seconds}{time}`;

function element(id) {
    return {
        id, hidden: id === "duel-notice", textContent: "", className: "", type: "", children: [], listeners: {},
        firstElementChild: null,
        replaceChildren(...children) { this.children = children; },
        append(...children) { this.children.push(...children); },
        addEventListener(kind, fn) { this.listeners[kind] = fn; },
        querySelector() { return actions; },
    };
}
const actions = element("actions");
const elements = {
    "duel-config": { textContent: JSON.stringify({ wsPath: "/duels/ws", pageUrl: "/duels", playUrl: "/play.html", rankedLevel: 25, minSeconds: 20, texts }) },
    "duel-notice": element("duel-notice"),
    "duel-notice-text": element("duel-notice-text"),
    "duel-notice-detail": element("duel-notice-detail"),
    "duel-online": element("duel-online"),
    "clan-duels": { textContent: JSON.stringify({ tags: { "2": "BET" }, rivals: [2] }) },
};
if (mode === "game" || mode === "aside" || mode === "claimed") {
    const container = element("game-player");
    container.firstElementChild = { startDuel: (...args) => { report.startDuel.push(args); return true; } };
    elements["game-player"] = container;
}
const report = { errors: [], sent: [], startDuel: [], notices: [], navigated: null, broadcasts: [], openedClan: [] };
let socket = null;
class FakeSocket {
    constructor(url) { this.url = url; this.readyState = 1; this.listeners = {}; socket = this; }
    addEventListener(kind, fn) { this.listeners[kind] = fn; }
    send(data) { report.sent.push(JSON.parse(data)); }
}
FakeSocket.OPEN = 1;
const channels = [];
class FakeChannel {
    constructor() { this.listeners = []; channels.push(this); }
    addEventListener(kind, fn) { this.listeners.push(fn); }
    removeEventListener() {}
    postMessage(data) { report.broadcasts.push(data); }
}
const documentListeners = {};
const context = {
    console, setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, String, Number, Boolean, Promise, Set,
    WebSocket: FakeSocket, BroadcastChannel: FakeChannel,
    navigator: {},
    location: { protocol: "http:", host: "localhost:5050", set href(value) { report.navigated = value; }, get href() { return "http://localhost:5050/"; } },
    document: {
        visibilityState: "visible",
        documentElement: { lang: "es" },
        getElementById: (id) => elements[id] || null,
        createElement: () => element("created"),
        addEventListener: (kind, fn) => { documentListeners[kind] = fn; },
    },
};
context.window = context;
context.addEventListener = () => {};
if (mode === "portal-game-open" || mode === "claimed") {  // marks left by another tab of this browser
    const store = {};
    if (mode === "portal-game-open") store["se-game-page"] = JSON.stringify({ page: "other", at: Date.now() });
    if (mode === "claimed") store["se-duel-launch"] = JSON.stringify({ duel: 9, page: "other", at: Date.now() });
    context.localStorage = {
        getItem: (key) => (key in store ? store[key] : null),
        setItem: (key, value) => { store[key] = String(value); },
        removeItem: (key) => { delete store[key]; },
    };
    report.store = store;
}
if (mode !== "portal") context.seOpenClan = (tab) => { report.openedClan.push(tab); };  // the game page's clan window
vm.createContext(context);
vm.runInContext(source.replace("try { onMessage(JSON.parse(event.data)); } catch (error) { /* ignore malformed messages */ }",
    "try { onMessage(JSON.parse(event.data)); } catch (error) { __report.errors.push(String(error && error.stack || error)); }"),
    Object.assign(context, { __report: report }));

function deliver(message) {
    socket.listeners.message({ data: JSON.stringify(message) });
    report.notices.push({ type: message.type, hidden: elements["duel-notice"].hidden, text: elements["duel-notice-text"].textContent,
        detail: elements["duel-notice-detail"].textContent });
}
const side = (id, name, extra) => ({ id, name, power: 1000, troops: 3, level: 30, report: "ok", percent: 50, seconds: 61,
    rating_before: 1000, rating_after: 1016, ...extra });

(async () => {
    deliver({ type: "hello", you: 1, online: [{ id: 1, name: "Ana", busy: false }, { id: 2, name: "Beto", busy: false }] });
    deliver({ type: "presence", online: [{ id: 2, name: "Beto", busy: true }] });
    const first = elements["duel-online"].children[0];
    report.onlineName = first && first.children[0] ? first.children[0].textContent : null;
    report.onlineRival = Boolean(first && first.children[0] && first.children[0].children.some((child) => child && child.className === "duels-rival"));
    deliver({ type: "clan_challenge", id: 4, best_of: 5, minutes: 10, clan: { tag: "ALF", name: "Alfa" }, url: "/clans/2" });
    deliver({ type: "clan_challenge_answer", id: 4, accepted: true, clan: { tag: "BET", name: "Beta" }, url: "/clans/1" });
    actions.children[0].listeners.click();  // "Ver reto"
    deliver({ type: "clan_alliance", id: 5, clan: { tag: "GAM", name: "Gama" }, url: "/clans/1" });
    actions.children[0].listeners.click();  // "Ver alianza"
    report.navigatedByClan = report.navigated;
    deliver({ type: "challenge_received", id: 7, other: { id: 2, name: "Beto" }, expires_in: 30 });
    deliver({ type: "challenge_sent", id: 8, other: { id: 2, name: "Beto" }, expires_in: 30 });
    deliver({ type: "challenge_closed", id: 8, reason: "declined", by: { id: 2, name: "Beto" } });
    deliver({ type: "error", code: "busy" });
    if (mode === "aside") {  // another game tab of this browser already opened the arena
        for (const channel of channels) for (const listener of channel.listeners) listener({ data: { type: "launched", id: 9 } });
    }
    deliver({ type: "duel_start", id: 9, side: "challenger", seconds_left: 600, ranked: true, arena: 100000040, tournament_type: 1,
        you: { id: 1, name: "Ana" }, other: { id: 2, name: "Beto" }, army: [509], enemy_army: [510] });
    if (documentListeners.visibilitychange) documentListeners.visibilitychange();  // the tab comes to the front at once
    report.afterStart = { text: elements["duel-notice-text"].textContent, detail: elements["duel-notice-detail"].textContent };
    await new Promise((resolve) => setTimeout(resolve, 1600));
    report.afterLaunch = { detail: elements["duel-notice-detail"].textContent };
    deliver({ type: "duel_waiting", id: 9, seconds_left: 300, other: { id: 2, name: "Beto" } });
    for (const status of ["done", "review", "void"]) {
        deliver({ type: "duel_result", id: 9, ranked: true, rated: status === "done", status, winner: status === "void" ? null : "challenger",
            review_reason: status === "review" ? "power" : status === "void" ? "no_reports" : null,
            challenger: side(1, "Ana"), defender: side(2, "Beto", { report: "missing", percent: null, seconds: null }) });
    }
    const container = elements["game-player"];
    report.gameRetired = Boolean(container && container.children.length && container.children[0].className === "duel-game-retired");
    console.log(JSON.stringify(report));
    process.exit(0);
})();
