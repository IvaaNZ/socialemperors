"use strict";
// In-game PvP window (SE_PVP=on): the game's "PvP" button (swf_pvp.py) opens it. Tabs: rivals
// (raid a village), raids (history) and duels (players online, challenge). Attacking or
// challenging first opens the game's own team window (window.sePickTeam): the chosen units
// fight. Names written by players go through esc() before they reach the page.
(function (root) {
    function esc(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }
    function fill(text, values) {
        return String(text || "").replace(/\{(\w+)\}/g, (match, key) => (key in values ? values[key] : match));
    }
    function number(value, lang) {
        const separator = lang === "en" ? "," : ".";
        return String(Math.trunc(Number(value) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, separator);
    }
    function percent(value, lang) {
        const text = (Math.round((Number(value) || 0) * 10) / 10).toString();
        return lang === "en" ? text : text.replace(".", ",");
    }
    function clock(seconds) {
        const total = Math.max(0, Math.ceil(seconds));
        const minutes = Math.floor(total / 60);
        return minutes + ":" + String(total % 60).padStart(2, "0");
    }
    function button(label, action, data, kind) {
        let attrs = ' data-action="' + esc(action) + '"';
        for (const key of Object.keys(data || {})) attrs += " data-" + key + '="' + esc(data[key]) + '"';
        return '<button type="button" class="clanx-btn' + (kind ? " clanx-btn-" + kind : "") + '"' + attrs + ">" + esc(label) + "</button>";
    }

    const View = {
        esc, fill,

        tabs(T, active) {
            return '<div class="clanx-tabs" role="tablist">' + [["rivals", T.tab_rivals], ["raids", T.tab_raids], ["duels", T.tab_duels]]
                .map(([key, label]) => '<button type="button" role="tab" class="clanx-tab' + (key === active ? " is-active" : "") +
                    '" aria-selected="' + (key === active) + '" data-tab="' + key + '">' + esc(label) + "</button>").join("") + "</div>";
        },

        rivals(T, state, lang, now, teamLimit) {
            const own = state.own;
            let html = '<p class="clanx-top"><strong>' + esc(fill(T.your_attack, { power: number(own.attack, lang), troops: own.troops })) +
                '</strong></p><p class="clanx-muted">' + esc(fill(T.choose_note, { count: teamLimit })) + "</p>";
            if (own.attack_available_at > now) {
                html += '<p class="clanx-warn">' + esc(fill(T.next_attack, { time: clock(own.attack_available_at - now) })) + "</p>";
            }
            if (!state.rivals.length) return html + '<p class="clanx-muted">' + esc(T.no_rivals) + "</p>";
            return html + '<ul class="clanx-list">' + state.rivals.map((rival) =>
                "<li><span><strong>" + esc(rival.name) + "</strong> · " + esc(fill(T.level, { level: rival.level })) + "<br>" +
                '<span class="clanx-muted">' + esc(fill(T.defense, { power: number(rival.defense, lang) })) + " · " +
                esc(fill(T.loot, { amount: number(rival.loot, lang) })) + "</span>" +
                (rival.can_attack ? "" : '<br><span class="clanx-muted">' + esc(rival.reason) + "</span>") + "</span><span>" +
                (rival.can_attack ? button(T.attack, "raid", { id: rival.id, token: rival.token }, "green") : "") + "</span></li>").join("") + "</ul>";
        },

        raids(T, state, lang) {
            if (!state.history.length) return '<p class="clanx-muted">' + esc(T.no_raids) + "</p>";
            return '<ul class="clanx-list clanx-small">' + state.history.map((entry) => {
                const key = entry.role === "attacker" ? (entry.won ? "raid_won" : "raid_lost") : (entry.won ? "robbed" : "defended");
                const good = entry.role === "attacker" ? entry.won : !entry.won;
                return '<li class="' + (good ? "is-won" : "is-lost") + '"><span><strong>' + esc(fill(T[key], { name: entry.name })) + "</strong><br>" +
                    '<span class="clanx-muted">' + esc(fill(T.raid_line, { mine: number(entry.mine, lang), theirs: number(entry.theirs, lang),
                        amount: number(entry.loot, lang) })) + "</span></span></li>";
            }).join("") + "</ul>";
        },

        duels(T, state, online, me, lang) {
            if (!state.duels) return '<p class="clanx-muted">' + esc(T.duels_off) + "</p>";
            const others = (online || []).filter((player) => player.id !== me);
            let html = '<p class="clanx-top"><strong>' + esc(fill(T.rating, { rating: number(state.duels.rating, lang) })) + "</strong></p>" +
                '<div class="clanx-card"><h3>' + esc(T.online) + "</h3>";
            html += others.length ? '<ul class="clanx-list">' + others.map((player) => "<li><span><strong>" + esc(player.name) + "</strong></span><span>" +
                (player.busy ? '<span class="clanx-chip">' + esc(T.busy) + "</span>" : button(T.challenge, "challenge", { id: player.id }, "green")) +
                "</span></li>").join("") + "</ul>" : '<p class="clanx-muted">' + esc(T.nobody) + "</p>";
            html += '</div><div class="clanx-card"><h3>' + esc(T.last_duels) + "</h3>";
            html += state.duels.history.length ? '<ul class="clanx-list clanx-small">' + state.duels.history.map((duel) =>
                '<li class="' + (duel.outcome === "won" ? "is-won" : duel.outcome === "lost" ? "is-lost" : "") + '"><span><strong>' +
                esc(fill(T["duel_" + duel.outcome], { name: duel.other })) + "</strong></span><span>" +
                esc(fill(T.duel_line, { mine: percent(duel.mine, lang), theirs: percent(duel.theirs, lang) })) + "</span></li>").join("") + "</ul>"
                : '<p class="clanx-muted">' + esc(T.no_duels) + "</p>";
            return html + "</div>";
        },
    };
    root.PvpOverlayView = View;
    if (typeof module !== "undefined" && module.exports) module.exports = View;

    // ---- controller (browser only) ----
    if (typeof document === "undefined") return;
    const configElement = document.getElementById("pvp-overlay-config");
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const T = config.texts;
    const lang = document.documentElement.lang || "es";
    const stage = document.querySelector(".game-stage") || document.body;
    let state = null;
    let tab = "rivals";
    let refreshTimer = null;
    let busy = false;

    // SE_STAY_IN_GAME (on unless turned off): nothing in the window leaves the game; it already has every tab.
    const stayInGame = document.body.hasAttribute("data-stay-in-game");
    const panel = document.createElement("div");
    panel.className = "clanx-overlay pvpx-overlay";
    panel.hidden = true;
    panel.innerHTML = '<div class="clanx-window" role="dialog" aria-modal="true" aria-labelledby="pvpx-title">' +
        '<div class="clanx-titlebar"><h2 id="pvpx-title">' + esc(T.title) + '</h2><button type="button" class="clanx-close" data-action="close" aria-label="' +
        esc(T.close) + '">×</button></div><div class="clanx-tabsbar"></div><div class="clanx-message" role="status" aria-live="polite" hidden></div>' +
        '<div class="clanx-body"></div>' + (stayInGame ? "" : '<p class="pvpx-portal"><a class="clanx-btn-link" href="' + esc(config.rivals) + '">' +
        esc(T.portal) + "</a></p>") + "</div>";
    stage.appendChild(panel);
    const tabsBar = panel.querySelector(".clanx-tabsbar");
    const body = panel.querySelector(".clanx-body");
    const messageBox = panel.querySelector(".clanx-message");

    function showMessage(text, ok) {
        messageBox.textContent = text || "";
        messageBox.className = "clanx-message " + (ok ? "is-ok" : "is-error");
        messageBox.hidden = !text;
    }

    function duels() {
        return window.seDuels || null;
    }

    function draw() {
        tabsBar.innerHTML = View.tabs(T, tab);
        if (!state) {
            body.innerHTML = '<p class="clanx-muted">' + esc(T.loading) + "</p>";
            return;
        }
        const now = Date.now() / 1000;
        if (tab === "rivals") body.innerHTML = View.rivals(T, state, lang, now, config.teamLimit);
        else if (tab === "raids") body.innerHTML = View.raids(T, state, lang);
        else body.innerHTML = View.duels(T, state, duels() ? duels().online() : [], duels() ? duels().me() : state.me, lang);
    }

    async function load() {
        try {
            const response = await fetch(config.state, { credentials: "same-origin", headers: { Accept: "application/json" } });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || T.error);
            state = data;
        } catch (error) {
            showMessage(error.message || T.error, false);
        }
        draw();
    }

    // The game's team window: resolves with the chosen unit ids, null when closed without choosing,
    // or undefined when the game cannot open it now (loading, an adventure, the arena).
    let teamResolve = null;
    window.seTeamSelected = (ids) => {
        const resolve = teamResolve;
        teamResolve = null;
        if (resolve) setTimeout(() => resolve(Array.isArray(ids) ? ids.map(Number).filter((id) => id > 0) : null), 0);
    };
    function pickTeam() {
        return new Promise((resolve) => {
            const game = stage.querySelector("ruffle-player, ruffle-object, ruffle-embed");
            let opened = false;
            try {
                opened = Boolean(game && typeof game.selectTeam === "function" && game.selectTeam());
            } catch (error) {
                opened = false;
            }
            if (!opened) {
                resolve(undefined);
                return;
            }
            teamResolve = resolve;
        });
    }
    window.sePickTeam = pickTeam;

    function hide() {
        panel.hidden = true;
        clearInterval(refreshTimer);
    }

    function open(wantedTab, message, ok) {
        if (wantedTab) tab = wantedTab;
        panel.hidden = false;
        showMessage(message || "", ok);
        draw();
        load();
        clearInterval(refreshTimer);
        refreshTimer = setInterval(() => { if (!panel.hidden && !busy) load(); }, 20000);
        panel.querySelector(".clanx-close").focus();
    }

    function close() {
        hide();
        const game = stage.querySelector("ruffle-player, ruffle-object, ruffle-embed");
        if (game) game.focus();
    }

    // Choose the team in the game (the window steps aside meanwhile), then run `then(team)`.
    async function withTeam(backTab, then) {
        if (busy) return;
        busy = true;
        hide();
        const team = await pickTeam();
        busy = false;
        if (team === undefined) { open(backTab, T.not_ready, false); return; }
        if (team === null) { open(backTab); return; }
        if (!team.length) { open(backTab, T.no_team, false); return; }
        then(team);
    }

    async function raid(id, token) {
        withTeam("rivals", async (team) => {
            const data = new FormData();
            data.append("csrf_token", config.csrf);
            data.append("defender_id", id);
            data.append("raid_token", token);
            data.append("army", JSON.stringify(team));
            try {
                const response = await fetch(config.raid, { method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" } });
                const answer = await response.json();
                if (!response.ok) throw new Error(answer.error || T.error);
                const result = answer.result;
                const text = result.won
                    ? fill(T.result_won, { name: result.defender_name, amount: number(result.total_loot, lang), troops: result.attacker_troops })
                    : fill(T.result_lost, { name: result.defender_name, mine: number(result.attacker_power, lang), theirs: number(result.defender_power, lang) });
                open("raids", text, result.won);
            } catch (error) {
                open("rivals", error.message || T.error, false);
            }
        });
    }

    function challenge(id) {
        const link = duels();
        if (!link) { open("duels", T.duels_off, false); return; }
        withTeam("duels", (team) => link.send({ type: "challenge", to: Number(id), army: team }));
    }

    window.seClosePvp = () => { if (!panel.hidden) close(); };
    window.seOpenPvp = (wanted) => {
        setTimeout(() => {
            if (busy) return;
            if (!wanted && !panel.hidden) close();
            else open(wanted);
        }, 0);
    };
    window.addEventListener("se-duels-online", () => { if (!panel.hidden && tab === "duels") draw(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !panel.hidden) close(); });
    panel.addEventListener("click", (event) => {
        if (event.target === panel) { close(); return; }
        const tabButton = event.target.closest("[data-tab]");
        if (tabButton) {
            tab = tabButton.dataset.tab;
            showMessage("", true);
            draw();
            load();
            return;
        }
        const target = event.target.closest("[data-action]");
        if (!target) return;
        const { action, id, token } = target.dataset;
        if (action === "close") close();
        else if (action === "raid") raid(id, token);
        else if (action === "challenge") challenge(id);
    });
})(typeof window !== "undefined" ? window : globalThis);
