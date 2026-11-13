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
    let retired = false;  // this game tab stood aside and closed its game (retireGame)
    const gameContainer = document.getElementById("game-player");
    // Clans (SE_CLANS=on): tags next to the names and the rivals of an active clan challenge.
    const clanElement = document.getElementById("clan-duels");
    const clanInfo = clanElement ? JSON.parse(clanElement.textContent) : { tags: {}, rivals: [] };
    const clanRivals = new Set(clanInfo.rivals || []);
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
                retireGame();
            }
            if (data.type === "taking-over" && gameContainer) {
                standingAside.add(data.id);
                if (launchedDuel !== data.id) {
                    stopLaunch();
                    showNotice(texts.going_to_game, texts.game_in_other_tab, [button(texts.close, hideNotice)]);
                    retireGame();
                }
            }
        });
    }
    const visible = () => document.visibilityState === "visible";

    // Which page of this browser opens a battle. BroadcastChannel messages arrive late, so
    // two game tabs could both open the arena, and a portal page could open a second game.
    // Pages leave marks in localStorage instead (read at once by every tab of the site):
    //  * a game page keeps "se-game-page" fresh while it is open (removed when it closes):
    //    a portal page then never opens a second copy of the game;
    //  * a game page claims a battle ("se-duel-launch") before opening it and keeps the
    //    claim fresh during the battle; another game page that finds it stands aside.
    // Without localStorage (private mode, blocked storage) the messages alone decide.
    const pageId = Math.random().toString(36).slice(2) + Date.now().toString(36);
    const storage = (() => {
        try {
            const store = window.localStorage;
            store.setItem("se-duels-test", "1");
            store.removeItem("se-duels-test");
            return store;
        } catch (error) {
            return null;
        }
    })();
    const GAME_KEY = "se-game-page";
    const LAUNCH_KEY = "se-duel-launch";
    const FRESH_MS = 75000;  // hidden tabs may run their timers only once a minute
    function readMark(key) {
        try { return JSON.parse(storage.getItem(key)); } catch (error) { return null; }
    }
    function writeMark(key, value) {
        try { storage.setItem(key, JSON.stringify(value)); } catch (error) { /* storage full or blocked */ }
    }
    function dropMark(key) {
        const mark = storage && readMark(key);
        if (mark && mark.page === pageId) {
            try { storage.removeItem(key); } catch (error) { /* blocked */ }
        }
    }
    const fresh = (mark) => Boolean(mark && mark.page !== pageId && Date.now() - mark.at < FRESH_MS);
    function otherGamePage() {
        return Boolean(storage) && fresh(readMark(GAME_KEY));
    }
    if (gameContainer && storage) {
        const beat = () => {
            if (retired) return;
            writeMark(GAME_KEY, { page: pageId, at: Date.now() });
            if (launchedDuel !== null) {
                const claim = readMark(LAUNCH_KEY);
                if (claim && claim.page === pageId) writeMark(LAUNCH_KEY, { duel: claim.duel, page: pageId, at: Date.now() });
            }
        };
        beat();
        setInterval(beat, 2000);
        window.addEventListener("pagehide", () => { dropMark(GAME_KEY); dropMark(LAUNCH_KEY); });
    }
    // Calls then(true) when this page may open the battle, then(false) when another one has it.
    function claimBattle(id, then) {
        if (!storage) { then(true); return; }
        const current = readMark(LAUNCH_KEY);
        if (current && current.duel === id && fresh(current)) { then(false); return; }
        writeMark(LAUNCH_KEY, { duel: id, page: pageId, at: Date.now() });
        // Two pages that wrote at the same moment: the last write wins, for both of them.
        setTimeout(() => {
            const winner = readMark(LAUNCH_KEY);
            then(Boolean(winner && winner.duel === id && winner.page === pageId));
        }, 300 + Math.floor(Math.random() * 300));
    }

    const fill = (text, values) => text.replace(/\{(\w+)\}/g, (match, key) => (key in values ? values[key] : match));
    // Same grouping as the portal's game_number filter: 6.925 (es, pt-BR) and 6,925 (en), always.
    const separator = (document.documentElement.lang || "es") === "en" ? "," : ".";
    const number = (value) => String(Math.trunc(Number(value) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, separator);
    const send = (message) => { if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message)); };
    // The in-game PvP window (pvp_overlay.js, SE_PVP=on) lists the players online and challenges through here.
    let online = [];
    window.seDuels = { online: () => online, me: () => me, send };

    function button(label, onClick, primary) {
        const element = document.createElement("button");
        element.type = "button";
        element.className = primary ? "duel-button duel-button-primary" : "duel-button";
        element.textContent = label;
        element.addEventListener("click", onClick);
        return element;
    }

    // A game tab that stood aside for the battle closes its game: two copies of the same
    // village would both send orders (the older one from an outdated state) and double the
    // memory the game takes. The player can open it again here with one click.
    function retireGame() {
        if (!gameContainer || retired) return;
        retired = true;
        const box = document.createElement("div");
        box.className = "duel-game-retired";
        const text = document.createElement("p");
        text.textContent = texts.game_closed_here;
        box.append(text, button(texts.reopen_game_here, () => window.location.reload(), true));
        if (gameContainer.dataset) gameContainer.dataset.retired = "true";  // game.js does not start it later either
        gameContainer.replaceChildren(box);  // removing the player stops the game
        if (storage) dropMark(GAME_KEY);  // no game here any more
    }

    // On the game page the clan notices open the in-game clan window instead of leaving the game.
    function openClan(url, tab) {
        if (typeof window.seOpenClan === "function") {
            hideNotice();
            window.seOpenClan(tab);
        } else {
            window.location.href = url;
        }
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
                retireGame();
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
                if (typeof window.seCloseClan === "function") window.seCloseClan();  // nothing over the battle
                if (typeof window.seClosePvp === "function") window.seClosePvp();
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
        if (otherGamePage()) {  // the game is already open in another tab: it opens the arena
            pendingStart = null;
            showNotice(fill(texts.starting, { name: message.other.name }), texts.game_in_other_tab, [button(texts.close, hideNotice)]);
            return;
        }
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
        claimBattle(message.id, (mine) => {
            if (mine) {
                launchBattle(message);
                return;
            }
            standingAside.add(message.id);  // another game tab of this browser has this battle
            showNotice(fill(texts.starting, { name: message.other.name }), texts.game_in_other_tab, [button(texts.close, hideNotice)]);
            retireGame();
        });
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

    function renderOnline(players) {
        online = players;
        if (typeof Event === "function" && typeof window.dispatchEvent === "function") window.dispatchEvent(new Event("se-duels-online"));
        if (!onlineList) return;
        const others = players.filter((player) => player.id !== me);
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
            const tag = clanInfo.tags && clanInfo.tags[String(player.id)];
            name.textContent = (tag ? "[" + tag + "] " : "") + player.name;
            item.append(name);
            if (clanRivals.has(player.id)) {
                const rival = document.createElement("span");
                rival.className = "duels-rival";
                rival.textContent = texts.clan_rival;
                name.append(" ", rival);
            }
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

    // SE_PVP=on, in the game: the answer comes with the team chosen in the game's team window.
    // Closed without choosing: the challenge stays open. Not in the village: the strongest troops fight.
    async function accept(id) {
        if (typeof window.sePickTeam !== "function") {
            send({ type: "respond", id, accept: true });
            return;
        }
        const notice = document.getElementById("duel-notice");
        if (notice) notice.hidden = true;
        const team = await window.sePickTeam();
        if (team === null || (Array.isArray(team) && !team.length)) {
            if (notice && pending === id) notice.hidden = false;
            return;
        }
        send(Array.isArray(team) ? { type: "respond", id, accept: true, army: team } : { type: "respond", id, accept: true });
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
                button(texts.accept, () => accept(message.id), true),
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
        case "clan_challenge": {
            const clanName = "[" + message.clan.tag + "] " + message.clan.name;
            showNotice(fill(texts.clan_challenge, { name: clanName }),
                fill(texts.clan_challenge_detail, { count: message.best_of, minutes: message.minutes }), [
                    button(texts.clan_challenge_open, () => openClan(message.url, "challenges"), true),
                    button(texts.close, hideNotice),
                ]);
            break;
        }
        case "clan_alliance": {
            const clanName = "[" + message.clan.tag + "] " + message.clan.name;
            showNotice(fill(texts.clan_alliance, { name: clanName }), "", [
                button(texts.clan_alliance_open, () => openClan(message.url, "clan"), true),
                button(texts.close, hideNotice),
            ]);
            break;
        }
        case "clan_challenge_answer": {
            const clanName = "[" + message.clan.tag + "] " + message.clan.name;
            showNotice(fill(message.accepted ? texts.clan_challenge_accepted : texts.clan_challenge_declined, { name: clanName }), "", [
                button(texts.clan_challenge_open, () => openClan(message.url, "challenges"), true),
                button(texts.close, hideNotice),
            ]);
            break;
        }
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
