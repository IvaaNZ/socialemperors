// Runs templates/js/duels.js in Node with a small fake DOM and feeds it every
// server message type; prints a JSON report. Used by tests/test_duels_js.py.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "..", "templates", "js", "duels.js"), "utf8");
const mode = process.argv[2] || "game";  // "game" (play page), "aside" (a second game tab) or "portal"
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
};
if (mode === "game" || mode === "aside") {
    const container = element("game-player");
    container.firstElementChild = { startDuel: (...args) => { report.startDuel.push(args); return true; } };
    elements["game-player"] = container;
}
const report = { errors: [], sent: [], startDuel: [], notices: [], navigated: null, broadcasts: [] };
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
    console.log(JSON.stringify(report));
    process.exit(0);
})();
