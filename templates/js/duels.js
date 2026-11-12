"use strict";
// Live duels (SE_DUELS=on): one WebSocket per page; texts come from the server
// in the viewer's language. Messages from the server carry codes and numbers.
// An accepted duel opens the tournament arena in the game page.
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
    let launchTimer = null;
    let pendingStart = null;  // a battle this page should take the player to
    let launchedDuel = null;
    const gameContainer = document.getElementById("game-player");
    // Pages of this player in this browser talk to each other (BroadcastChannel):
    // the page the player is looking at takes them to the arena, and the other
    // pages stand aside so only one opens it.
    const pages = typeof BroadcastChannel === "function" ? new BroadcastChannel("se-duels") : null;
    const standingAside = new Set();
    if (pages) {
        pages.addEventListener("message", (event) => {
            const data = event.data || {};
            if (data.type === "launched" && !gameContainer && pendingStart && pendingStart.id === data.id) {
                pendingStart = null;  // another tab of this browser already opened the arena
                showNotice(texts.going_to_game, texts.game_in_other_tab, [button(texts.close, hideNotice)]);
            }
            if (data.type === "launched" && gameContainer && launchedDuel !== data.id) {
                standingAside.add(data.id);  // another game tab of this browser opened the arena
                pendingStart = null;
            }
            if (data.type === "taking-over" && gameContainer) {
                standingAside.add(data.id);
                if (launchedDuel !== data.id) {
                    stopLaunch();
                    showNotice(texts.going_to_game, texts.game_in_other_tab, [button(texts.close, hideNotice)]);
                }
            }
        });
    }
    const visible = () => document.visibilityState === "visible";

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

    // Counts down to a fixed end time: a background tab gets few timer ticks, so
    // never count ticks.
    const secondsUntil = (endAt) => Math.max(0, Math.ceil((endAt - Date.now()) / 1000));

    function startCountdown(seconds, base) {
        const endAt = Date.now() + seconds * 1000;
        const render = () => { noticeDetail.textContent = fill(texts.seconds, { seconds: secondsUntil(endAt) }) + (base ? " · " + base : ""); };
        render();
        countdown = setInterval(render, 1000);
    }

    const clock = (seconds) => {
        const total = Math.max(0, Math.round(Number(seconds) || 0));
        return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
    };

    function stopLaunch() {
        clearTimeout(launchTimer);
        launchTimer = null;
    }

    // The game page opens the arena through the movie's callback (swf_duel_bridge.py);
    // it answers false until the home village is loaded, so keep trying until the deadline.
    function launchBattle(message) {
        stopLaunch();
        const deadline = Date.now() + message.seconds_left * 1000;
        const started = Date.now();
        const attempt = () => {
            if (standingAside.has(message.id)) {
                showNotice(fill(texts.starting, { name: message.other.name }), texts.game_in_other_tab, [button(texts.close, hideNotice)]);
                return;
            }
            const player = gameContainer && gameContainer.firstElementChild;
            let opened = false;
            try {
                if (player && typeof player.startDuel === "function") {
                    opened = player.startDuel(message.id, message.tournament_type, message.other.id, message.other.name,
                        message.army, message.enemy_army, message.you.name) === true;
                }
            } catch (error) { /* the movie is still loading */ }
            if (opened) {
                pendingStart = null;
                if (pages) pages.postMessage({ type: "launched", id: message.id });
                launchTimer = setTimeout(hideNotice, 6000);
                return;
            }
            if (Date.now() - started > 15000) noticeDetail.textContent = texts.game_not_ready;
            if (Date.now() < deadline) launchTimer = setTimeout(attempt, 1000);
        };
        attempt();
    }

    function goToGame(message) {
        if (pages) pages.postMessage({ type: "taking-over", id: message.id });
        showNotice(fill(texts.starting, { name: message.other.name }), texts.going_to_game, [button(texts.close, hideNotice)]);
        setTimeout(() => { window.location.href = config.playUrl; }, 1200);
    }

    function openArena(message) {
        if (launchedDuel === message.id) return;
        if (standingAside.has(message.id)) {
            showNotice(fill(texts.starting, { name: message.other.name }), texts.game_in_other_tab, [button(texts.close, hideNotice)]);
            return;
        }
        launchedDuel = message.id;  // a second call (visibility change, reconnection) does nothing
        showNotice(fill(texts.starting, { name: message.other.name }), fill(texts.arena_help, { name: message.other.name }),
            [button(texts.close, hideNotice)]);
        launchBattle(message);
    }

    // The page the player is looking at takes them to the arena: a portal page
    // goes to the game, a game page opens the arena. With no page in sight, the
    // game page opens it after a moment (unless a portal page took over).
    function onDuelStart(message) {
        pending = null;
        pendingStart = message;
        if (!gameContainer) {
            if (visible()) goToGame(message);
            return;
        }
        if (visible()) {
            openArena(message);
            return;
        }
        setTimeout(() => { if (pendingStart === message) openArena(message); }, 1500);
    }

    document.addEventListener("visibilitychange", () => {
        const message = pendingStart;
        if (!message || !visible() || launchedDuel === message.id) return;
        if (gameContainer) openArena(message);
        else goToGame(message);
    });

    function onDuelWaiting(message) {
        stopLaunch();
        pendingStart = null;
        showNotice(fill(texts.waiting, { name: message.other.name }), "", [button(texts.close, hideNotice)]);
        const endAt = Date.now() + message.seconds_left * 1000;
        const render = () => { noticeDetail.textContent = fill(texts.time_left, { time: clock(secondsUntil(endAt)) }); };
        render();
        countdown = setInterval(render, 1000);
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

    function reportLine(player) {
        const values = { name: player.name, percent: number(player.percent), time: clock(player.seconds), seconds: config.minSeconds };
        const key = player.report === "ok" ? "line" : "line_" + (player.report || "missing");
        return fill(texts[key] || texts.line_invalid, values);
    }

    function showResult(result) {
        stopLaunch();
        pendingStart = null;
        const mySide = result.challenger.id === me ? "challenger" : "defender";
        const mine = result[mySide];
        const theirs = result[mySide === "challenger" ? "defender" : "challenger"];
        let title;
        if (result.status === "void" || result.status === "review") title = texts[result.status];
        else title = result.winner === "draw" ? texts.draw : result.winner === mySide ? texts.won : texts.lost;
        const lines = [reportLine(mine), reportLine(theirs)];
        if (result.rated) lines.push(fill(texts.ranked, { before: number(mine.rating_before), after: number(mine.rating_after) }));
        else if (result.status === "review") lines.push(texts.review_detail);
        else if (result.status === "void") lines.push(result.review_reason === "restart" ? texts.void_restart : texts.void_detail);
        else if (!result.ranked) lines.push(fill(texts.friendly, { level: config.rankedLevel }));
        else lines.push(texts.not_rated);
        showMessage(fill(title, { name: theirs.name }), lines.join(" · "));
        send({ type: "seen", id: result.id });  // the server stops sending it again
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
        case "duel_start":
            onDuelStart(message);
            break;
        case "duel_waiting":
            onDuelWaiting(message);
            break;
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
