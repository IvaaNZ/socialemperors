"use strict";
// The Soul Mixer's window (SE_SOUL_MIXER): tapping the building in the game (swf_soul_mixer.py) opens it. The player
// picks two units of the village; the server (soul_mixer.py) rolls the result, shown as a silhouette, which power-ups
// move up; "Mix" sends the two units into the mixer for good; after the wait (or paying it away) "Get unit" puts the
// new unit in the gifts. Starting, finishing early and collecting change the village: the window offers to reload it.
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
    function picture(unit, size) {
        return unit && unit.thumb ? '<img src="' + esc(unit.thumb) + '" alt="" width="' + size + '" height="' + size + '" loading="lazy">'
            : '<span class="smx-noimg" aria-hidden="true">?</span>';
    }
    function slot(unit, label, extra) {
        return '<div class="smx-slot' + (extra || "") + '">' + picture(unit, 84) + "<span>" + esc(label) + "</span></div>";
    }

    const View = {
        esc, fill, duration,

        // The stage: the two souls, then the result (a silhouette until it is ready).
        stage(T, art, first, second, result, hidden, resultLabel) {
            const empty = { thumb: art.empty };
            return '<div class="smx-stage" style="background-image:url(\'' + esc(art.background) + '\')">' +
                slot(first || empty, first ? first.name : T.empty) + '<span class="smx-plus" aria-hidden="true">+</span>' +
                slot(second || empty, second ? second.name : T.empty) + '<span class="smx-plus" aria-hidden="true">=</span>' +
                (result ? slot(result, resultLabel || result.name, " is-result")
                    : '<div class="smx-slot is-result"><span class="smx-mystery' + (hidden ? " is-glowing" : "") + '" aria-hidden="true">?</span><span>' +
                        esc(resultLabel || "?") + "</span></div>") + "</div>";
        },

        pick(T, art, state, picked, lang) {
            const first = picked.length ? state.eligible.find((unit) => unit.id === picked[0]) : null;
            let html = View.stage(T, art, first, null, null, false) + '<p class="clanx-muted">' + esc(T.intro) + "</p>";
            if (!state.eligible.length) return html + '<p class="clanx-muted">' + esc(T.no_units) + "</p>";
            html += "<h3>" + esc(picked.length ? T.pick_second : T.pick_first) + '</h3><div class="smx-grid">';
            return html + state.eligible.map((unit) => {
                const used = picked.filter((id) => id === unit.id).length;
                const free = unit.count - used;
                return '<button type="button" class="smx-unit' + (used ? " is-picked" : "") + '" data-action="pick" data-unit="' + unit.id +
                    '"' + (free > 0 ? "" : " disabled") + ">" + picture(unit, 64) + '<span class="smx-count">' + esc(fill(T.count, { count: number(unit.count, lang) })) +
                    "</span><span>" + esc(unit.name) + "</span></button>";
            }).join("") + "</div>";
        },

        preview(T, art, state, lang) {
            const p = state.preview;
            return View.stage(T, art, p.parents[0], p.parents[1], null, true, T.mystery) +
                '<p class="clanx-muted">' + esc(T.mystery_help) + " " + esc(fill(T.upgrades, { count: p.upgrades })) + " · " +
                esc(fill(T.powerup_help, { cash: number(p.total, lang) })) + "</p>" +
                '<div class="smx-actions"><button type="button" class="clanx-btn clanx-btn-green" data-action="start">' + esc(T.start) + "</button>" +
                '<button type="button" class="clanx-btn" data-action="powerup">' + esc(fill(T.powerup, { cash: number(p.next_price, lang) })) + "</button>" +
                '<button type="button" class="clanx-btn" data-action="clear">' + esc(T.change) + "</button></div>" +
                '<p class="clanx-muted">' + esc(fill(T.cash, { cash: number(state.cash, lang) })) + "</p>";
        },

        mixing(T, art, state, lang) {
            const m = state.mix;
            const ready = !m.remaining && !!m.result;
            let html = View.stage(T, art, m.parents[0], m.parents[1], ready ? m.result : null, true, ready ? m.result && m.result.name : T.mystery);
            if (ready) {
                return html + '<p class="smx-time">' + esc(T.ready) + '</p><div class="smx-actions"><button type="button" class="clanx-btn clanx-btn-green" data-action="collect">' +
                    esc(T.collect) + "</button></div>";
            }
            return html + '<p class="smx-time">' + esc(fill(T.mixing, { name: T.mystery })) + " · " + esc(fill(T.ready_in, { time: duration(T, m.remaining) })) + "</p>" +
                '<div class="smx-actions"><button type="button" class="clanx-btn clanx-btn-green" data-action="speed_up">' +
                esc(fill(T.speed_up, { cash: number(m.speed_price, lang) })) + "</button></div>" +
                '<p class="clanx-muted">' + esc(fill(T.cash, { cash: number(state.cash, lang) })) + "</p>";
        },

        help(T, art) {
            return '<div class="smx-help">' + art.help.map((src) => '<img src="' + esc(src) + '" alt="" loading="lazy">').join("") + "</div>" +
                '<div class="smx-actions"><button type="button" class="clanx-btn" data-action="help">' + esc(T.back) + "</button></div>";
        },

        body(T, art, state, picked, lang) {
            if (!state.has_mixer) return '<p class="clanx-muted">' + esc(T.errors.no_mixer) + "</p>";
            if (state.level < state.min_level) return '<p class="clanx-muted">' + esc(fill(T.errors.level, { level: state.min_level })) + "</p>";
            if (state.mix) return View.mixing(T, art, state, lang);
            if (state.preview) return View.preview(T, art, state, lang);
            return View.pick(T, art, state, picked, lang);
        },
    };
    root.SoulMixerOverlayView = View;
    if (typeof module !== "undefined" && module.exports) module.exports = View;

    // ---- controller (browser only) ----
    if (typeof document === "undefined") return;
    const configElement = document.getElementById("soul-mixer-overlay-config");
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const T = config.texts;
    const lang = document.documentElement.lang || "es";
    const stage = document.querySelector(".game-stage") || document.body;
    let state = null;
    let picked = [];
    let help = false;
    let busy = false;
    let ticker = null;

    const panel = document.createElement("div");
    panel.className = "clanx-overlay smx-overlay";
    panel.hidden = true;
    panel.innerHTML = '<div class="clanx-window" role="dialog" aria-modal="true" aria-labelledby="smx-title">' +
        '<div class="clanx-titlebar"><h2 id="smx-title">' + esc(T.title) + '</h2><button type="button" class="clanx-btn" data-action="help">' + esc(T.help) +
        '</button><button type="button" class="clanx-close" data-action="close" aria-label="' + esc(T.close) + '">×</button></div>' +
        '<div class="clanx-message" role="status" aria-live="polite" hidden></div><div class="clanx-body"><div class="smx-content"></div></div></div>';
    stage.appendChild(panel);
    const content = panel.querySelector(".smx-content");
    const messageBox = panel.querySelector(".clanx-message");

    function showMessage(html, ok) {
        messageBox.innerHTML = html || "";
        messageBox.className = "clanx-message " + (ok ? "is-ok" : "is-error");
        messageBox.hidden = !html;
    }

    function reloadLink(text) {
        return esc(text) + ' <a class="clanx-btn clanx-btn-green smx-reload" href="' + esc(config.play) + '">' + esc(T.reload) + "</a>";
    }

    function draw() {
        if (help) { content.innerHTML = View.help(T, config.art); return; }
        content.innerHTML = state ? View.body(T, config.art, state, picked, lang) : '<p class="clanx-muted">' + esc(T.loading) + "</p>";
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

    async function act(action, fields) {
        if (busy) return;
        busy = true;
        const data = new FormData();
        data.append("csrf_token", config.csrf);
        data.append("action", action);
        Object.entries(fields || {}).forEach(([key, value]) => data.append(key, value));
        try {
            const response = await fetch(config.action, { method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" } });
            const answer = await response.json();
            if (answer.state) state = answer.state;
            if (!response.ok) throw new Error(answer.error || T.error);
            showMessage("", true);
            if (action === "collect" && answer.unit) showMessage(reloadLink(fill(T.collected, { name: answer.unit.name })), true);
            else if (action === "start") showMessage(reloadLink(T.started + " " + T.reload_help), true);
            else if (action === "speed_up") showMessage(reloadLink(T.sped_up + " " + T.reload_help), true);
        } catch (error) {
            showMessage(esc(error.message || T.error), false);
        }
        picked = [];
        busy = false;
        draw();
    }

    function tick() {  // the wait counts down while the window is open
        if (panel.hidden || !state || !state.mix || !state.mix.remaining) return;
        state.mix.remaining = Math.max(0, state.mix.remaining - 1);
        if (!state.mix.remaining || state.mix.remaining % 60 === 0) draw();
    }

    function open() {
        panel.hidden = false;
        help = false;
        picked = [];
        showMessage("", true);
        draw();
        load();
        clearInterval(ticker);
        ticker = setInterval(tick, 1000);
        panel.querySelector(".clanx-close").focus();
    }

    function close() {
        panel.hidden = true;
        clearInterval(ticker);
        const game = stage.querySelector("ruffle-player, ruffle-object, ruffle-embed");
        if (game) game.focus();
    }

    window.seSoulMixerLimit = () => T.errors.one_mixer;  // the game asks, to say why a second one is not placed
    window.seOpenSoulMixer = () => { setTimeout(() => { if (panel.hidden) open(); }, 0); };
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !panel.hidden) close(); });
    panel.addEventListener("click", (event) => {
        if (event.target === panel) { close(); return; }
        const target = event.target.closest("[data-action]");
        if (!target || target.disabled) return;
        const action = target.dataset.action;
        if (action === "close") close();
        else if (action === "help") { help = !help; draw(); }
        else if (action === "pick") {
            picked.push(Number(target.dataset.unit));
            if (picked.length === 2) act("choose", { first: picked[0], second: picked[1] });
            else draw();
        } else if (action === "start") {
            if (window.confirm(T.start_confirm)) act("start");
        } else act(action);
    });
})(typeof window !== "undefined" ? window : globalThis);
