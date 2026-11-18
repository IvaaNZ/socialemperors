// Adventures alone or with the clan (SE_COOP=on; COOP_PLAN.md phase 1): the choice before sailing and the clan
// raid's room. The game asks with window.seCoopChoose() (swf_coop.py) and waits; the answer is
// player.seCoopGo(clan). A team chosen in the game's window comes back through window.seCoopPicked(quest, army):
// with an island it opens a room, without one it is a guest's team. The server (coop_web.py) keeps the room and
// tells the others live ('se-live' events from duels.js).
(() => {
    "use strict";

    const configElement = document.getElementById("coop-overlay-config");
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const T = config.texts;
    const stage = document.querySelector(".game-stage") || document.body;
    let state = null;
    let pending = null;   // "create" (the host's team for a new room) or a room id (a guest's team)
    let panelOpen = false;

    const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const fill = (text, values) => String(text).replace(/\{(\w+)\}/g, (_, key) => (key in values ? values[key] : ""));
    const player = () => {
        const host = document.getElementById("game-player");
        return host && host.firstChild;
    };
    const button = (label, action, kind, extra) =>
        '<button type="button" class="clanx-btn' + (kind ? " clanx-btn-" + kind : "") + '" data-action="' + action + '"' + (extra || "") + ">" + esc(label) + "</button>";

    // ---- the server
    async function load() {
        try {
            const response = await fetch(config.state, { credentials: "same-origin", cache: "no-store" });
            if (response.ok) state = await response.json();
        } catch (error) {
            // offline for a moment: the next round
        }
        return state;
    }

    async function act(fields) {
        const data = new FormData();
        data.append("csrf_token", config.csrf);
        for (const [key, value] of Object.entries(fields)) data.append(key, value);
        try {
            const response = await fetch(config.action, { method: "POST", body: data, credentials: "same-origin" });
            const result = await response.json();
            if (result.state) state = result.state;
            if (!result.ok) showMessage(T.errors[result.error] || T.errors.forbidden);
            return result.ok ? result : null;
        } catch (error) {
            showMessage(T.errors.forbidden);
            return null;
        }
    }

    // ---- the windows
    const choice = document.createElement("div");
    choice.className = "clanx-overlay coop-choice";
    choice.hidden = true;
    stage.appendChild(choice);

    const panel = document.createElement("div");
    panel.className = "clanx-overlay coop-room";
    panel.hidden = true;
    panel.innerHTML = '<div class="clanx-window" role="dialog" aria-modal="true" aria-labelledby="coop-title">' +
        '<div class="clanx-titlebar"><h2 id="coop-title">' + esc(T.room_title) + '</h2><button type="button" class="clanx-close" data-action="hide" aria-label="' +
        esc(T.close) + '">×</button></div><div class="clanx-message" role="status" aria-live="polite" hidden></div><div class="clanx-body"></div></div>';
    stage.appendChild(panel);
    const body = panel.querySelector(".clanx-body");
    const messageBox = panel.querySelector(".clanx-message");

    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "coop-chip";
    chip.hidden = true;
    chip.addEventListener("click", () => openPanel());
    stage.appendChild(chip);

    const notice = document.createElement("div");
    notice.className = "coop-notice";
    notice.hidden = true;
    stage.appendChild(notice);

    function showMessage(text, ok) {
        messageBox.textContent = text || "";
        messageBox.className = "clanx-message " + (ok ? "is-ok" : "is-error");
        messageBox.hidden = !text;
        if (text && !panelOpen) showNotice(text, [button(T.close, "notice-close")]);
    }

    function showNotice(text, buttons, detail) {
        notice.innerHTML = '<p class="coop-notice-title">' + esc(text) + "</p>" + (detail ? '<p class="coop-notice-detail">' + esc(detail) + "</p>" : "") +
            '<div class="clanx-actions">' + buttons.join("") + "</div>";
        notice.hidden = false;
    }

    function showChoice(clanMessage) {
        choice.innerHTML = '<div class="clanx-window coop-choice-window" role="dialog" aria-modal="true" aria-labelledby="coop-choice-title">' +
            '<div class="clanx-titlebar"><h2 id="coop-choice-title">' + esc(T.adventure) + '</h2><button type="button" class="clanx-close" data-action="choice-cancel" aria-label="' +
            esc(T.cancel) + '">×</button></div><div class="clanx-body"><p class="coop-question">' + esc(T.choose_title) + "</p>" +
            '<div class="coop-modes">' +
            '<button type="button" class="coop-mode" data-action="solo"><strong>' + esc(T.solo) + "</strong><span>" + esc(T.solo_detail) + "</span></button>" +
            '<button type="button" class="coop-mode" data-action="clan"><strong>' + esc(T.clan) + "</strong><span>" + esc(T.clan_detail) + "</span></button>" +
            "</div>" + (clanMessage ? '<p class="clanx-message is-error">' + esc(clanMessage) + "</p>" : "") + "</div></div>";
        choice.hidden = false;
    }

    function render() {
        const room = state && state.room;
        chip.hidden = !room;
        if (room) chip.textContent = T.room_title + " · " + fill(T.players, { count: room.players.filter((p) => p.state !== "invited").length, max: room.max });
        if (!panelOpen) return;
        if (!room) {
            body.innerHTML = "<p>" + esc(T.room_closed) + '</p><div class="clanx-actions">' + button(T.close, "hide") + "</div>";
            return;
        }
        const label = { host: T.host, invited: T.invited, accepted: T.accepted };
        if (room.status === "sailing") {
            const host = room.players.find((p) => p.id === room.host);
            body.innerHTML = '<p class="coop-sailing">' + esc(room.is_host ? T.sailing_host : fill(T.sailing_guest, { name: host ? host.name : "" })) +
                '</p><ul class="coop-players">' + room.players.map((p) => '<li><strong>' + esc(p.name) + '</strong> <span class="coop-state">' +
                esc(label[p.state] || "") + '</span> <span class="coop-units">' + esc(fill(T.units, { count: p.units })) + "</span></li>").join("") +
                '</ul><div class="clanx-actions">' + button(room.is_host ? T.end_raid : T.leave, "leave", "red") + "</div>";
            return;
        }
        let html = '<div class="clanx-card"><h3>' + esc(fill(T.players, { count: room.players.filter((p) => p.state !== "invited").length, max: room.max })) + "</h3><ul class=\"coop-players\">";
        for (const p of room.players) {
            const units = p.state === "invited" ? "" : p.units ? fill(T.units, { count: p.units }) : T.choosing;
            html += '<li><span class="coop-dot ' + (p.online ? "is-online" : "") + '" title="' + esc(p.online ? T.online : T.offline) + '"></span>' +
                "<strong>" + esc(p.name) + '</strong> <span class="coop-state">' + esc(label[p.state] || "") + '</span> <span class="coop-units">' + esc(units) + "</span></li>";
        }
        html += "</ul></div>";
        if (room.is_host) {
            const inRoom = new Set(room.players.map((p) => p.id));
            const free = room.players.length < room.max;
            const candidates = (state.members || []).filter((m) => !inRoom.has(m.id));
            html += '<div class="clanx-card"><h3>' + esc(T.members) + "</h3>";
            if (!candidates.some((m) => m.online)) html += "<p>" + esc(T.nobody) + "</p>";
            html += '<ul class="coop-players">';
            for (const m of candidates) {
                html += '<li><span class="coop-dot ' + (m.online ? "is-online" : "") + '"></span><strong>' + esc(m.name) + "</strong> " +
                    (m.online && free ? button(T.invite, "invite", "brown", ' data-account="' + m.id + '"') : '<span class="coop-state">' + esc(m.online ? "" : T.offline) + "</span>") + "</li>";
            }
            html += "</ul></div>";
            html += '<div class="clanx-actions">' + button(T.change_team, "my-team", "brown") +
                button(T.sail, "sail", "green", room.can_sail ? "" : " disabled") + button(T.close_room, "leave", "red") + "</div>" +
                (room.can_sail ? "" : '<p class="coop-note">' + esc(T.waiting) + "</p>");
        } else {
            html += '<div class="clanx-actions">' + button(T.change_team, "my-team", "brown") + button(T.leave, "leave", "red") + "</div>" +
                '<p class="coop-note">' + esc(room.can_sail ? T.waiting_host : T.waiting) + "</p>";
        }
        body.innerHTML = html;
    }

    function openPanel() {
        panelOpen = true;
        panel.hidden = false;
        messageBox.hidden = true;
        render();
    }

    function hidePanel() {
        panelOpen = false;
        panel.hidden = true;
    }

    function pickTeam(target) {
        const game = player();
        let opened = false;
        try {
            opened = Boolean(game && typeof game.seCoopPick === "function" && game.seCoopPick());
        } catch (error) {
            opened = false;
        }
        if (!opened) {
            showMessage(T.not_village);
            return;
        }
        pending = target;
        hidePanel();
    }

    // ---- what the game says
    window.seCoopChoose = function () {
        showChoice("");
        load();
        return true;  // the game waits for seCoopGo
    };

    window.seCoopPicked = function (quest, army) {
        // Answered later: the game's call must return at once.
        setTimeout(async () => {
            const target = pending;
            pending = null;
            if (!Array.isArray(army)) {
                if (state && state.room) openPanel();
                return;
            }
            if (quest !== null && quest !== undefined) {
                if (await act({ action: "create", quest: String(quest), team: JSON.stringify(army) })) openPanel();
            } else if (target) {
                if (await act({ action: "team", room: target, team: JSON.stringify(army) })) openPanel();
            }
            render();
        }, 0);
    };

    // ---- clicks
    choice.addEventListener("click", async (event) => {
        const target = event.target.closest("[data-action]");
        if (!target) return;
        const game = player();
        switch (target.dataset.action) {
        case "solo":
            choice.hidden = true;
            if (game) game.seCoopGo(false);
            break;
        case "clan":
            if (!state) await load();
            if (!state || !state.clan) {
                showChoice(T.no_clan);
                break;
            }
            choice.hidden = true;
            pending = "create";
            if (game) game.seCoopGo(true);
            break;
        case "choice-cancel":
            choice.hidden = true;
            break;
        default:
            break;
        }
    });

    panel.addEventListener("click", async (event) => {
        const target = event.target.closest("[data-action]");
        if (!target || target.disabled) return;
        const room = state && state.room;
        switch (target.dataset.action) {
        case "hide":
            hidePanel();
            break;
        case "invite":
            if (room) await act({ action: "invite", room: room.id, account: target.dataset.account });
            render();
            break;
        case "my-team":
            if (room) pickTeam(room.id);
            break;
        case "leave":
            if (room && await act({ action: "leave", room: room.id })) hidePanel();
            render();
            break;
        case "sail": {
            if (!room) break;
            const result = await act({ action: "sail", room: room.id });
            if (!result) break;
            let landed = false;
            try {
                const game = player();
                const answer = game && typeof game.seCoopSail === "function" ? game.seCoopSail(result.quest, result.army) : false;
                landed = answer === true;
                if (!landed) console.warn("coop: the game did not set sail:", answer);  // false: no island kept; text: the game's error
            } catch (error) {
                landed = false;
            }
            if (landed) hidePanel();
            else showMessage(T.no_island);
            render();
            break;
        }
        default:
            break;
        }
    });

    notice.addEventListener("click", async (event) => {
        const target = event.target.closest("[data-action]");
        if (!target) return;
        const roomId = target.dataset.room;
        switch (target.dataset.action) {
        case "accept":
            notice.hidden = true;
            if (await act({ action: "respond", room: roomId, accept: "1" })) pickTeam(roomId);
            render();
            break;
        case "decline":
            notice.hidden = true;
            await act({ action: "respond", room: roomId, accept: "0" });
            render();
            break;
        default:
            notice.hidden = true;
            break;
        }
    });

    function showInvites() {
        const invite = state && state.invites && state.invites[0];
        if (!invite || (state.room && state.room.id)) return;
        showNotice(fill(T.invite_title, { name: invite.host }), [
            button(T.accept, "accept", "green", ' data-room="' + invite.room + '"'),
            button(T.decline, "decline", "", ' data-room="' + invite.room + '"'),
        ], T.invite_detail);
    }

    window.addEventListener("se-live", async (event) => {
        const message = event.detail || {};
        if (message.type === "coop_invite") {
            await load();
            showInvites();
            render();
        } else if (message.type === "coop_update") {
            await load();
            render();
        } else if (message.type === "coop_sail") {  // the host set sail: the guests see the raid at sea
            await load();
            openPanel();
        }
    });

    load().then(() => {
        showInvites();
        render();
    });
    setInterval(async () => {  // without live notices (duels off), the room still follows
        if (state && (state.room || panelOpen)) {
            await load();
            render();
        }
    }, 15000);
})();
