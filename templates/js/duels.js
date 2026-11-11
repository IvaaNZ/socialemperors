"use strict";
// Live duels (SE_DUELS=on): one WebSocket per page; texts come from the server
// in the viewer's language. Messages from the server carry codes and numbers.
(() => {
    const configElement = document.getElementById("duel-config");
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const texts = config.texts;
    const notice = document.getElementById("duel-notice");
    const noticeText = document.getElementById("duel-notice-text");
    const noticeDetail = document.getElementById("duel-notice-detail");
    const noticeActions = notice.querySelector(".duel-notice-actions");
    const onlineList = document.getElementById("duel-online");
    let socket = null;
    let me = null;
    let retryDelay = 1000;
    let countdown = null;
    let pending = null;

    const fill = (text, values) => text.replace(/\{(\w+)\}/g, (match, key) => (key in values ? values[key] : match));
    // Same grouping as the portal's game_number filter: 6.925 (es, pt-BR) and 6,925 (en), always.
    const separator = (document.documentElement.lang || "es") === "en" ? "," : ".";
    const number = (value) => String(Math.trunc(Number(value) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, separator);
    const send = (message) => { if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message)); };

    function button(label, onClick, primary) {
        const element = document.createElement("button");
        element.type = "button";
        element.className = primary ? "duel-button duel-button-primary" : "duel-button";
        element.textContent = label;
        element.addEventListener("click", onClick);
        return element;
    }

    function hideNotice() {
        clearInterval(countdown);
        countdown = null;
        pending = null;
        notice.hidden = true;
    }

    function showNotice(text, detail, actions) {
        clearInterval(countdown);
        countdown = null;
        noticeText.textContent = text;
        noticeDetail.textContent = detail || "";
        noticeActions.replaceChildren(...actions);
        notice.hidden = false;
    }

    function showMessage(text, detail) {
        pending = null;
        showNotice(text, detail, [button(texts.close, hideNotice)]);
    }

    function startCountdown(seconds, base) {
        let left = seconds;
        const render = () => { noticeDetail.textContent = fill(texts.seconds, { seconds: left }) + (base ? " · " + base : ""); };
        render();
        countdown = setInterval(() => { left = Math.max(0, left - 1); render(); }, 1000);
    }

    function renderOnline(online) {
        if (!onlineList) return;
        const others = online.filter((player) => player.id !== me);
        if (!others.length) {
            const empty = document.createElement("li");
            empty.className = "duels-empty";
            empty.textContent = texts.nobody;
            onlineList.replaceChildren(empty);
            return;
        }
        onlineList.replaceChildren(...others.map((player) => {
            const item = document.createElement("li");
            const name = document.createElement("span");
            name.textContent = player.name;
            item.append(name);
            if (player.busy) {
                const busy = document.createElement("span");
                busy.className = "duels-busy";
                busy.textContent = texts.busy_label;
                item.append(busy);
            } else {
                item.append(button(texts.challenge, () => send({ type: "challenge", to: player.id }), true));
            }
            return item;
        }));
    }

    function showResult(result) {
        const mine = result.challenger.id === me ? result.challenger : result.defender;
        const theirs = result.challenger.id === me ? result.defender : result.challenger;
        const mySide = result.challenger.id === me ? "challenger" : "defender";
        const title = result.winner === "draw" ? texts.draw : result.winner === mySide ? texts.won : texts.lost;
        let detail = fill(texts.powers, { mine: number(mine.power), name: theirs.name, theirs: number(theirs.power) });
        detail += " · " + (result.ranked
            ? fill(texts.ranked, { before: number(mine.rating_before), after: number(mine.rating_after) })
            : fill(texts.friendly, { level: config.rankedLevel }));
        showMessage(fill(title, { name: theirs.name }), detail);
    }

    function onMessage(message) {
        switch (message.type) {
        case "hello":
            me = message.you;
            renderOnline(message.online);
            break;
        case "presence":
            renderOnline(message.online);
            break;
        case "challenge_received":
            pending = message.id;
            showNotice(fill(texts.received, { name: message.other.name }), "", [
                button(texts.accept, () => send({ type: "respond", id: message.id, accept: true }), true),
                button(texts.decline, () => { send({ type: "respond", id: message.id, accept: false }); hideNotice(); }),
            ]);
            startCountdown(message.expires_in);
            break;
        case "challenge_sent":
            pending = message.id;
            showNotice(fill(texts.sent, { name: message.other.name }), "", [
                button(texts.cancel, () => send({ type: "cancel", id: message.id })),
            ]);
            startCountdown(message.expires_in);
            break;
        case "challenge_closed": {
            const name = message.by ? message.by.name : "";
            const text = { declined: texts.declined, expired: texts.expired, disconnected: texts.disconnected }[message.reason] || texts.cancelled;
            if (message.reason === "declined" && message.by && message.by.id === me) { hideNotice(); break; }
            showMessage(fill(text, { name }));
            break;
        }
        case "duel_result":
            showResult(message);
            break;
        case "error":
            showMessage(texts["error_" + message.code] || texts.error_invalid);
            break;
        default:
            break;
        }
    }

    function connect() {
        const scheme = location.protocol === "https:" ? "wss:" : "ws:";
        const target = /^wss?:/.test(config.wsPath) ? config.wsPath : scheme + "//" + location.host + config.wsPath;
        socket = new WebSocket(target);
        socket.addEventListener("open", () => { retryDelay = 1000; });
        socket.addEventListener("message", (event) => {
            try { onMessage(JSON.parse(event.data)); } catch (error) { /* ignore malformed messages */ }
        });
        socket.addEventListener("close", () => {
            if (onlineList) {
                const offline = document.createElement("li");
                offline.className = "duels-empty";
                offline.textContent = texts.offline;
                onlineList.replaceChildren(offline);
            }
            setTimeout(connect, retryDelay);
            retryDelay = Math.min(retryDelay * 2, 10000);
        });
    }

    connect();
})();
