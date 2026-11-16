"use strict";
// In-game season pass window (SE_SEASON_PASS): the game's "Pase" button (swf_season_pass.py) opens it. Tabs: the
// rewards of the 40 levels (claim one or all of the reached ones) and the daily and weekly challenges. Claiming
// changes the village: the page then pauses the game and asks to reload it (game.js), like a treasury claim.
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
    function duration(T, seconds) {
        const total = Math.max(0, Math.floor(seconds));
        const days = Math.floor(total / 86400);
        const hours = Math.floor((total % 86400) / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        if (days) return fill(T.days, { days }) + " " + fill(T.hours, { hours });
        if (hours) return fill(T.hours, { hours }) + " " + fill(T.minutes, { minutes });
        return fill(T.minutes, { minutes: Math.max(1, minutes) });
    }
    function percent(part, whole) {
        return Math.max(0, Math.min(100, whole ? (part / whole) * 100 : 0)).toFixed(1);
    }

    const View = {
        esc, fill, duration,

        rewardText(T, reward, lang) {
            if (reward.unit) return '<span class="spx-unit">' + esc(fill(T.unit, { name: reward.name || reward.unit })) + "</span>";
            if (reward.cash) return esc(fill(T.cash, { amount: number(reward.cash, lang) }));
            return esc(fill(T.resources[reward.resource] || "{amount}", { amount: number(reward.amount, lang) }));
        },

        tabs(T, active) {
            return '<div class="clanx-tabs" role="tablist">' + [["rewards", T.tab_rewards], ["challenges", T.tab_challenges]]
                .map(([key, label]) => '<button type="button" role="tab" class="clanx-tab' + (key === active ? " is-active" : "") +
                    '" aria-selected="' + (key === active) + '" data-tab="' + key + '">' + esc(label) + "</button>").join("") + "</div>";
        },

        head(T, state, lang) {
            const full = state.level >= state.levels;
            return '<div class="spx-head"><div class="spx-badge" aria-hidden="true">' + esc(state.level) + '</div><div class="spx-head-text">' +
                "<strong>" + esc(fill(T.level_of, { level: state.level, levels: state.levels })) + "</strong>" +
                '<div class="spx-bar" role="progressbar" aria-valuemin="0" aria-valuemax="' + state.per_level + '" aria-valuenow="' +
                state.level_points + '"><span style="width:' + percent(state.level_points, state.per_level) + '%"></span></div>' +
                '<span class="clanx-muted">' + esc(full ? T.max_level : fill(T.points, { points: number(state.level_points, lang),
                    total: number(state.per_level, lang) })) + " · " + esc(fill(T.ends_in, { time: duration(T, state.ends_in) })) +
                "</span></div></div>";
        },

        rewards(T, state, lang) {
            const ready = state.rewards.filter((row) => row.reached && !row.claimed).length;
            let html = '<p class="clanx-muted">' + esc(T.how) + "</p>";
            if (ready) html += '<p class="spx-claim-all"><button type="button" class="clanx-btn clanx-btn-green" data-action="claim" data-level="all">' +
                esc(fill(T.claim_all, { count: ready })) + "</button></p>";
            return html + '<ul class="clanx-list spx-ladder">' + state.rewards.map((row) => {
                const kind = row.claimed ? "is-claimed" : row.reached ? "is-ready" : "is-locked";
                const action = row.claimed ? '<span class="clanx-chip">' + esc(T.claimed) + "</span>"
                    : row.reached ? '<button type="button" class="clanx-btn clanx-btn-green" data-action="claim" data-level="' + row.level + '">' + esc(T.claim) + "</button>"
                        : '<span class="clanx-muted">' + esc(T.locked) + "</span>";
                const icon = row.reward.icon ? '<img class="spx-icon" src="' + esc(row.reward.icon) + '" alt="" width="40" height="40" loading="lazy">'
                    : '<span class="spx-icon"></span>';
                return '<li class="' + kind + (row.reward.unit ? " is-unit" : "") + '"><span class="spx-level">' + row.level +
                    "</span>" + icon + '<span class="spx-reward">' + View.rewardText(T, row.reward, lang) + "</span><span>" + action + "</span></li>";
            }).join("") + "</ul>";
        },

        challenges(T, state, lang) {
            const block = (title, next, list) => '<div class="clanx-card"><h3>' + esc(title) + '</h3><p class="clanx-muted">' + esc(next) + "</p>" +
                list.map((challenge) => '<div class="spx-challenge' + (challenge.done ? " is-done" : "") + '"><div class="spx-challenge-row"><span>' +
                    esc(fill((challenge.target === 1 && T.challenges_one && T.challenges_one[challenge.event]) || T.challenges[challenge.event] || challenge.event,
                        { target: number(challenge.target, lang) })) + '</span><span class="spx-points">' +
                    esc(challenge.done ? T.done : fill(T.reward_points, { points: number(challenge.points, lang) })) + '</span></div><div class="spx-bar"><span style="width:' +
                    percent(challenge.progress, challenge.target) + '%"></span></div><span class="clanx-muted">' + number(challenge.progress, lang) + " / " +
                    number(challenge.target, lang) + "</span></div>").join("") + "</div>";
            return '<p class="clanx-muted">' + esc(fill(T.play_today, { points: number(state.play_today, lang), cap: number(state.play_cap, lang) })) + "</p>" +
                block(T.daily, fill(T.daily_in, { time: duration(T, state.daily_in) }), state.daily) +
                block(T.weekly, fill(T.weekly_in, { time: duration(T, state.weekly_in) }), state.weekly);
        },
    };
    root.SeasonPassOverlayView = View;
    if (typeof module !== "undefined" && module.exports) module.exports = View;

    // ---- controller (browser only) ----
    if (typeof document === "undefined") return;
    const configElement = document.getElementById("season-pass-overlay-config");
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const T = config.texts;
    const lang = document.documentElement.lang || "es";
    const stage = document.querySelector(".game-stage") || document.body;
    let state = null;
    let tab = "rewards";
    let busy = false;

    const panel = document.createElement("div");
    panel.className = "clanx-overlay spx-overlay";
    panel.hidden = true;
    panel.innerHTML = '<div class="clanx-window" role="dialog" aria-modal="true" aria-labelledby="spx-title">' +
        '<div class="clanx-titlebar"><h2 id="spx-title">' + esc(T.title) + '</h2><button type="button" class="clanx-close" data-action="close" aria-label="' +
        esc(T.close) + '">×</button></div><div class="clanx-message" role="status" aria-live="polite" hidden></div>' +
        '<div class="clanx-body"><div class="spx-top"></div><div class="clanx-tabsbar"></div><div class="spx-content"></div></div></div>';
    stage.appendChild(panel);
    const title = panel.querySelector("#spx-title");
    const top = panel.querySelector(".spx-top");
    const tabsBar = panel.querySelector(".clanx-tabsbar");
    const content = panel.querySelector(".spx-content");
    const messageBox = panel.querySelector(".clanx-message");

    function showMessage(html, ok) {
        messageBox.innerHTML = html || "";
        messageBox.className = "clanx-message " + (ok ? "is-ok" : "is-error");
        messageBox.hidden = !html;
    }

    function draw() {
        tabsBar.innerHTML = View.tabs(T, tab);
        if (!state) {
            top.innerHTML = "";
            content.innerHTML = '<p class="clanx-muted">' + esc(T.loading) + "</p>";
            return;
        }
        title.textContent = fill(T.season, { season: T.seasons[state.season] || state.name, year: state.year });
        top.innerHTML = View.head(T, state, lang);
        content.innerHTML = tab === "rewards" ? View.rewards(T, state, lang) : View.challenges(T, state, lang);
    }

    async function load() {
        try {
            const response = await fetch(config.state, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || T.error);
            state = data;
        } catch (error) {
            showMessage(esc(error.message || T.error), false);
        }
        draw();
    }

    async function claim(level) {
        if (busy) return;
        busy = true;
        const data = new FormData();
        data.append("csrf_token", config.csrf);
        data.append("level", level);
        try {
            const response = await fetch(config.claim, { method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" } });
            const answer = await response.json();
            if (!response.ok) throw new Error(answer.error || T.error);
            state = answer.state;
            if (answer.given.length) {
                showMessage(esc(fill(T.received, { count: answer.given.length })) + ' <a class="clanx-btn clanx-btn-green spx-reload" href="' +
                    esc(config.play) + '">' + esc(T.reload) + "</a>", true);
            }
        } catch (error) {
            showMessage(esc(error.message || T.error), false);
        }
        busy = false;
        draw();
    }

    function open() {
        panel.hidden = false;
        showMessage("", true);
        draw();
        load();
        panel.querySelector(".clanx-close").focus();
    }

    function close() {
        panel.hidden = true;
        const game = stage.querySelector("ruffle-player, ruffle-object, ruffle-embed");
        if (game) game.focus();
    }

    window.seCloseSeasonPass = () => { if (!panel.hidden) close(); };
    window.seOpenSeasonPass = () => {
        setTimeout(() => {
            if (!panel.hidden) close();
            else open();
        }, 0);
    };
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !panel.hidden) close(); });
    panel.addEventListener("click", (event) => {
        if (event.target === panel) { close(); return; }
        const tabButton = event.target.closest("[data-tab]");
        if (tabButton) {
            tab = tabButton.dataset.tab;
            draw();
            return;
        }
        const target = event.target.closest("[data-action]");
        if (!target) return;
        if (target.dataset.action === "close") close();
        else if (target.dataset.action === "claim") claim(target.dataset.level);
    });
})(typeof window !== "undefined" ? window : globalThis);
