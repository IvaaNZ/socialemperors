"use strict";
// The global chat (block G, SE_CHAT): a "Msj" button at the left of the game, below the clock, with a dot that is
// red when someone else wrote something not seen yet and grey otherwise. It opens the chat window: the last messages
// ("[TAG] Name (level)"), a box to write and Send. New and deleted messages arrive live ("se-live" events from the
// duels' connection, duels.js); the page also asks again every few seconds in case that connection is down.
(function (root) {
    function esc(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }
    function fill(text, values) {
        return String(text || "").replace(/\{(\w+)\}/g, (match, key) => (key in values ? values[key] : match));
    }
    function localTime(seconds) {  // the end of a mute, in the player's own hour
        return new Date(seconds * 1000).toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    }
    function mutedText(T, until) {
        return until ? fill(T.muted, { time: localTime(until) }) : T.muted_forever;
    }
    function clock(seconds) {
        const date = new Date(seconds * 1000);
        return String(date.getHours()).padStart(2, "0") + ":" + String(date.getMinutes()).padStart(2, "0");
    }

    const View = {
        esc, fill,
        author(message) {
            return (message.tag ? "[" + message.tag + "] " : "") + message.name + (message.level ? " (" + message.level + ")" : "");
        },
        message(T, message, me) {
            const mine = message.from === me;
            return '<li class="gchat-msg' + (mine ? " is-mine" : "") + '" data-id="' + message.id + '"><div class="gchat-meta"><strong>' +
                esc(View.author(message)) + '</strong><time>' + esc(clock(message.at)) + '</time></div><p>' + esc(message.text) + "</p></li>";
        },
        list(T, messages, me) {
            if (!messages.length) return '<li class="gchat-empty">' + esc(T.empty) + "</li>";
            return messages.map((message) => View.message(T, message, me)).join("");
        },
    };
    root.GlobalChatView = View;
    if (typeof module !== "undefined" && module.exports) module.exports = View;

    // ---- controller (browser only) ----
    if (typeof document === "undefined") return;
    const configElement = document.getElementById("chat-overlay-config");
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const T = config.texts;
    const stage = document.querySelector(".game-stage") || document.body;
    let me = null;
    let messages = [];
    let unread = false;
    let muted = false;
    let busy = false;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "gchat-button";
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H10l-5 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/></svg>' +
        '<span class="gchat-label">' + esc(T.button) + '</span><span class="gchat-dot" aria-hidden="true"></span>';
    stage.appendChild(button);

    const panel = document.createElement("div");
    panel.className = "gchat-panel";
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-labelledby", "gchat-title");
    panel.innerHTML = '<div class="gchat-head"><h2 id="gchat-title">' + esc(T.title) + '</h2><button type="button" class="gchat-close" aria-label="' +
        esc(T.close) + '">×</button></div><ol class="gchat-list" aria-live="polite"><li class="gchat-empty">' + esc(T.loading) +
        '</li></ol><p class="gchat-note" role="status" hidden></p><form class="gchat-form"><label class="sr-only" for="gchat-text">' + esc(T.placeholder) +
        '</label><input id="gchat-text" name="text" autocomplete="off" maxlength="' + config.length + '" placeholder="' + esc(T.placeholder) +
        '"><button type="submit">' + esc(T.send) + "</button></form>";
    stage.appendChild(panel);
    const list = panel.querySelector(".gchat-list");
    const note = panel.querySelector(".gchat-note");
    const form = panel.querySelector(".gchat-form");
    const input = panel.querySelector("#gchat-text");

    function setUnread(value) {
        unread = value;
        button.classList.toggle("has-unread", unread);
        button.title = unread ? T.unread : T.no_unread;
        button.setAttribute("aria-label", T.button + " · " + (unread ? T.unread : T.no_unread));
    }

    function showNote(text) {
        note.textContent = text || "";
        note.hidden = !text;
    }

    function place() {  // below the clock (game.js places it), with the same size; at the left edge otherwise
        const clockBox = document.getElementById("hud-clock");
        const stageBox = stage.getBoundingClientRect();
        let left = 12, top = 140, scale = 1;
        if (clockBox && !clockBox.hidden) {
            const box = clockBox.getBoundingClientRect();
            scale = parseFloat(clockBox.style.getPropertyValue("--hud-scale")) || 1;
            left = box.left - stageBox.left;
            top = box.bottom - stageBox.top + 8 * scale;
        }
        button.style.setProperty("--hud-scale", scale.toFixed(3));
        button.style.left = left + "px";
        button.style.top = top + "px";
        panel.style.setProperty("--hud-scale", scale.toFixed(3));
        panel.style.left = left + "px";
        panel.style.top = top + "px";
    }

    function draw(scrollDown) {
        const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
        list.innerHTML = View.list(T, messages, me);
        if (scrollDown || atBottom) list.scrollTop = list.scrollHeight;
        input.disabled = muted;
    }

    async function post(url, fields) {
        const data = new FormData();
        data.append("csrf_token", config.csrf);
        Object.entries(fields).forEach(([key, value]) => data.append(key, value));
        const response = await fetch(url, { method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" } });
        const answer = await response.json().catch(() => ({}));
        if (!response.ok) {
            if (answer.code === "muted" || answer.code === "muted_forever") {
                muted = true;
                input.disabled = true;
                throw new Error(mutedText(T, answer.code === "muted" ? answer.until : 0));
            }
            throw new Error(answer.message || T.error);
        }
        return answer;
    }

    function markRead() {
        if (panel.hidden || !messages.length) return;
        setUnread(false);
        post(config.read, { last: messages[messages.length - 1].id }).catch(() => {});
    }

    async function load(scrollDown) {
        try {
            const response = await fetch(config.state, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
            if (!response.ok) return;
            const state = await response.json();
            me = state.me;
            messages = state.messages;
            muted = state.muted;
            setUnread(state.unread && panel.hidden);
            if (!panel.hidden) {
                draw(scrollDown);
                showNote(muted ? mutedText(T, state.muted_until) : "");
                markRead();
            }
        } catch {
            // the next look tries again
        }
    }

    function open() {
        panel.hidden = false;
        button.setAttribute("aria-expanded", "true");
        place();
        draw(true);
        load(true);
        setTimeout(() => input.focus(), 0);
    }

    function close() {
        panel.hidden = true;
        button.setAttribute("aria-expanded", "false");
        showNote("");
        const game = stage.querySelector("ruffle-player, ruffle-object, ruffle-embed");
        if (game) game.focus();
    }

    button.addEventListener("click", () => (panel.hidden ? open() : close()));
    panel.querySelector(".gchat-close").addEventListener("click", close);
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !panel.hidden) close(); });
    // Keys typed in the chat must not reach the game (its shortcuts).
    panel.addEventListener("keydown", (event) => event.stopPropagation());
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text || busy) return;
        busy = true;
        try {
            const answer = await post(config.send, { text });
            input.value = "";
            showNote("");
            if (!messages.some((message) => message.id === answer.message.id)) messages.push(answer.message);
            draw(true);
        } catch (error) {
            showNote(error.message);
        }
        busy = false;
        input.focus();
    });

    window.addEventListener("se-live", (event) => {
        const message = event.detail || {};
        if (message.type === "chat_message" && message.message) {
            if (messages.some((row) => row.id === message.message.id)) return;
            messages.push(message.message);
            if (messages.length > 100) messages.shift();
            if (panel.hidden) {
                if (message.message.from !== me) setUnread(true);
            } else {
                draw(false);
                markRead();
            }
        } else if (message.type === "chat_deleted") {
            messages = messages.filter((row) => row.id !== message.id);
            if (!panel.hidden) draw(false);
        }
    });

    place();
    window.addEventListener("resize", place);
    setInterval(place, 1000);  // the clock moves when the resource bar or the window changes
    setUnread(false);
    load(false);
    setInterval(() => { if (document.visibilityState === "visible") load(false); }, config.poll * 1000);
})(typeof window !== "undefined" ? window : globalThis);
