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

    // ---- phase 3: the guests watch the host's island live, as video (WebRTC, browser to browser). The host's
    // page sends its game's canvas to every guest that asks ("join"); the server only relays the connection
    // messages (coop_signal). The guest sees it over its own game.
    const peers = new Map();   // the host: guest id -> RTCPeerConnection
    let guestPeer = null;      // a guest: its connection to the host
    let joinTimer = 0;

    async function signal(to, payload) {
        const data = new FormData();
        data.append("csrf_token", config.csrf);
        data.append("to", to);
        data.append("payload", JSON.stringify(payload));
        try {
            await fetch(config.signal, { method: "POST", body: data, credentials: "same-origin" });
        } catch (error) {
            // the next try
        }
    }

    let earlyIce = [];  // a guest: network candidates that came before the host's offer

    function newPeer(other) {
        const peer = new RTCPeerConnection({ iceServers: config.ice || [] });
        peer.pendingIce = [];
        peer.onicecandidate = (event) => { if (event.candidate) signal(other, { kind: "ice", candidate: event.candidate.toJSON() }); };
        return peer;
    }

    // Candidates may arrive before the other side's description: kept until it is set.
    async function addIce(peer, candidate) {
        if (peer.remoteDescription) await peer.addIceCandidate(candidate);
        else peer.pendingIce.push(candidate);
    }

    async function setRemote(peer, sdp) {
        await peer.setRemoteDescription(sdp);
        for (const candidate of peer.pendingIce.splice(0)) await peer.addIceCandidate(candidate);
    }

    function gameCanvas() {
        const game = player();
        return game && game.shadowRoot ? game.shadowRoot.querySelector("canvas") : null;
    }

    async function hostAnswerJoin(guest) {
        const canvas = gameCanvas();
        if (!canvas || typeof canvas.captureStream !== "function") return;
        const old = peers.get(guest);
        if (old) old.close();
        const peer = newPeer(guest);
        peers.set(guest, peer);
        const stream = canvas.captureStream(20);
        for (const track of stream.getTracks()) peer.addTrack(track, stream);
        // phase 4: the guest's units go to it and its orders come back on a data channel of the same connection
        peer.channel = peer.createDataChannel("coop");
        peer.channel.onmessage = (event) => hostTakeOrder(guest, event.data);
        const offer = await peer.createOffer();
        await peer.setLocalDescription(offer);
        signal(guest, { kind: "offer", sdp: peer.localDescription.toJSON() });
    }

    // ---- phase 4, the host: whose unit is each one, the guests' units to them, their orders to the game
    const owners = new Map();  // handle -> account id, for the raid
    let ownerCounts = null;    // account id -> {unit id: how many still to find}

    function stageSize() {
        try {
            const view = player().seView();
            if (view && view.sw) return { w: view.sw, h: view.sh };
        } catch (error) {
            // below
        }
        return null;
    }

    function ownerOf(unit, room) {
        if (owners.has(unit.h)) return owners.get(unit.h);
        if (!ownerCounts) {
            ownerCounts = new Map();
            const ordered = room.players.filter((p) => p.state === "host").concat(room.players.filter((p) => p.state === "accepted"));
            for (const p of ordered) {
                const counts = {};
                for (const id of p.team || []) counts[id] = (counts[id] || 0) + 1;
                ownerCounts.set(p.id, counts);
            }
        }
        // the army lands the host's units first, then each guest's: the first ones of a kind are the host's
        let owner = room.host;
        for (const [account, counts] of ownerCounts) {
            if (counts[unit.id] > 0) {
                counts[unit.id] -= 1;
                owner = account;
                break;
            }
        }
        owners.set(unit.h, owner);
        return owner;
    }

    const reportedDeaths = new Set();  // handles already told to the server (it counts each once anyway)
    let lastBuff = 0;

    async function reportDeath(room, unit, owner) {
        reportedDeaths.add(unit.h);
        const data = new FormData();
        data.append("csrf_token", config.csrf);
        data.append("room", room.id);
        data.append("handle", unit.h);
        data.append("owner", owner);
        data.append("unit", unit.id);
        try {
            await fetch(config.death, { method: "POST", body: data, credentials: "same-origin" });
        } catch (error) {
            reportedDeaths.delete(unit.h);  // the next round tries again
        }
    }

    function onIsland(game) {  // the island is loaded (not the home village: gameMode 1)
        try {
            const hud = game.seHudState();
            return Boolean(hud) && hud.mode !== 1;
        } catch (error) {
            return false;
        }
    }

    // The host, every 250 ms during a raid: the raid's units (deaths go to the server with their owner), the
    // island's enemies strengthened for the players beyond the first (point 30), and each guest its own units.
    function hostShareUnits() {
        const room = state && state.room;
        if (!room || !room.is_host || room.status !== "sailing") return;
        const game = player();
        const size = stageSize();
        if (!game || !size || typeof game.seCoopUnits !== "function" || !onIsland(game)) return;
        const players = room.players.filter((p) => p.state === "host" || p.state === "accepted").length;
        if (players > 1 && Date.now() - lastBuff > 1000) {
            lastBuff = Date.now();
            try {
                game.seCoopBuff(1 + (config.difficulty || 0) * (players - 1));
            } catch (error) {
                // the next second
            }
        }
        let units = null;
        try {
            units = game.seCoopUnits();
        } catch (error) {
            units = null;
        }
        if (!Array.isArray(units)) return;
        const mine = new Map();
        for (const unit of units) {
            const owner = ownerOf(unit, room);
            if (unit.d) {
                if (!reportedDeaths.has(unit.h)) reportDeath(room, unit, owner);
                continue;
            }
            if (owner === room.host) continue;
            if (!mine.has(owner)) mine.set(owner, []);
            mine.get(owner).push({ h: unit.h, x: unit.x / size.w, y: unit.y / size.h, hp: unit.max > 0 ? unit.hp / unit.max : 1 });
        }
        for (const [guest, peer] of peers) {
            if (peer.channel && peer.channel.readyState === "open") {  // (no guest watching: nothing to send)
                peer.channel.send(JSON.stringify({ type: "units", units: mine.get(guest) || [] }));
            }
        }
    }
    setInterval(hostShareUnits, 250);

    function hostTakeOrder(guest, data) {
        let order = null;
        try {
            order = JSON.parse(data);
        } catch (error) {
            return;
        }
        const size = stageSize();
        const game = player();
        if (!order || order.type !== "order" || !Array.isArray(order.units) || !size || !game) return;
        const handles = order.units.filter((h) => Number.isInteger(h) && owners.get(h) === guest);  // only its own units
        const x = Number(order.x);
        const y = Number(order.y);
        if (!handles.length || !(x >= 0 && x <= 1 && y >= 0 && y <= 1)) return;
        try {
            const answer = game.seCoopOrder(handles, x * size.w, y * size.h);
            if (answer !== true) console.warn("coop: the game did not take the order:", answer);
        } catch (error) {
            console.warn("coop order:", error);
        }
    }

    const viewer = document.createElement("div");
    viewer.className = "coop-viewer";
    viewer.hidden = true;
    viewer.innerHTML = '<div class="coop-viewer-bar"><span class="coop-viewer-title"></span><span class="coop-viewer-units"></span>' +
        button(T.all_units, "select-all", "brown") + button(T.leave, "viewer-leave", "red") +
        '</div><div class="coop-screen"><video class="coop-video" autoplay playsinline muted></video><div class="coop-marks"></div></div>' +
        '<p class="coop-hint">' + esc(T.command_hint) + '</p><p class="coop-viewer-note" hidden></p>';
    stage.appendChild(viewer);
    const video = viewer.querySelector("video");
    const viewerTitle = viewer.querySelector(".coop-viewer-title");
    const viewerNote = viewer.querySelector(".coop-viewer-note");
    const marks = viewer.querySelector(".coop-marks");
    const unitsLabel = viewer.querySelector(".coop-viewer-units");

    // ---- phase 4, a guest: its units over the video; a touch on one chooses it, a touch elsewhere orders
    let guestChannel = null;
    let myUnits = [];
    const chosen = new Set();

    function pictureBox() {  // where the picture is inside the video element (object-fit: contain)
        const box = video.getBoundingClientRect();
        const vw = video.videoWidth || 1;
        const vh = video.videoHeight || 1;
        const scale = Math.min(box.width / vw, box.height / vh);
        const w = vw * scale;
        const h = vh * scale;
        return { left: (box.width - w) / 2, top: (box.height - h) / 2, w, h };
    }

    function drawUnits() {
        const pic = pictureBox();
        for (const h of [...chosen]) if (!myUnits.some((unit) => unit.h === h)) chosen.delete(h);
        marks.innerHTML = myUnits.map((unit) => '<button type="button" class="coop-mark' + (chosen.has(unit.h) ? " is-chosen" : "") +
            '" data-unit="' + unit.h + '" style="left:' + (pic.left + unit.x * pic.w).toFixed(1) + "px;top:" + (pic.top + unit.y * pic.h).toFixed(1) +
            'px"><span class="coop-mark-life" style="width:' + Math.round(Math.max(0, Math.min(1, unit.hp)) * 100) + '%"></span></button>').join("");
        unitsLabel.textContent = myUnits.length ? fill(T.my_units, { count: myUnits.length }) : T.none_alive;
    }

    function sendOrder(x, y) {
        if (!guestChannel || guestChannel.readyState !== "open" || !myUnits.length) return;
        const units = chosen.size ? [...chosen] : myUnits.map((unit) => unit.h);
        guestChannel.send(JSON.stringify({ type: "order", units, x, y }));
        const ping = document.createElement("span");  // where the order went
        ping.className = "coop-ping";
        const pic = pictureBox();
        ping.style.left = (pic.left + x * pic.w) + "px";
        ping.style.top = (pic.top + y * pic.h) + "px";
        marks.appendChild(ping);
        setTimeout(() => ping.remove(), 700);
    }

    marks.addEventListener("click", (event) => {
        const mark = event.target.closest(".coop-mark");
        if (mark) {
            const h = Number(mark.dataset.unit);
            if (event.shiftKey || event.ctrlKey) {
                if (chosen.has(h)) chosen.delete(h); else chosen.add(h);
            } else {
                chosen.clear();
                chosen.add(h);
            }
            drawUnits();
            return;
        }
        const pic = pictureBox();
        const box = marks.getBoundingClientRect();
        const x = (event.clientX - box.left - pic.left) / pic.w;
        const y = (event.clientY - box.top - pic.top) / pic.h;
        if (x >= 0 && x <= 1 && y >= 0 && y <= 1) sendOrder(x, y);
    });

    function hostName(room) {
        const host = room && room.players.find((p) => p.id === room.host);
        return host ? host.name : "";
    }

    // The host may still be loading the island when a guest asks: the guest asks again every 5 s (4 times), then
    // says so and offers to try again.
    function guestJoin(attempt = 1) {
        const room = state && state.room;
        if (!room || room.status !== "sailing" || room.is_host) return;
        viewer.hidden = false;
        hidePanel();
        viewerTitle.textContent = fill(T.connecting, { name: hostName(room) });
        viewerNote.hidden = true;
        signal(room.host, { kind: "join" });
        clearTimeout(joinTimer);
        joinTimer = setTimeout(() => {
            if (video.srcObject) return;
            if (attempt < 4) {
                guestJoin(attempt + 1);
                return;
            }
            viewerNote.innerHTML = esc(T.no_video) + " " + button(T.retry, "viewer-retry", "brown");
            viewerNote.hidden = false;
        }, 5000);
    }

    async function guestTakeOffer(from, sdp) {
        if (guestPeer) guestPeer.close();
        guestPeer = newPeer(from);
        guestPeer.ondatachannel = (event) => {
            guestChannel = event.channel;
            guestChannel.onmessage = (message) => {
                try {
                    const data = JSON.parse(message.data);
                    if (data.type === "units" && Array.isArray(data.units)) {
                        myUnits = data.units;
                        drawUnits();
                    }
                } catch (error) {
                    // a broken message: the next one
                }
            };
        };
        guestPeer.ontrack = (event) => {
            video.srcObject = event.streams[0];
            viewerTitle.textContent = fill(T.watching, { name: hostName(state && state.room) });
            viewerNote.hidden = true;
        };
        guestPeer.pendingIce.push(...earlyIce.splice(0));
        await setRemote(guestPeer, sdp);
        const answer = await guestPeer.createAnswer();
        await guestPeer.setLocalDescription(answer);
        signal(from, { kind: "answer", sdp: guestPeer.localDescription.toJSON() });
    }

    function stopVideo() {
        for (const peer of peers.values()) peer.close();
        peers.clear();
        if (guestPeer) guestPeer.close();
        guestPeer = null;
        guestChannel = null;
        myUnits = [];
        chosen.clear();
        owners.clear();
        ownerCounts = null;
        reportedDeaths.clear();
        earlyIce = [];
        video.srcObject = null;
        viewer.hidden = true;
        clearTimeout(joinTimer);
    }

    async function onSignal(message) {
        const payload = message.payload || {};
        const room = state && state.room;
        try {
            if (payload.kind === "join" && room && room.is_host && room.status === "sailing") {
                await hostAnswerJoin(message.from);
            } else if (payload.kind === "offer") {
                await guestTakeOffer(message.from, payload.sdp);
            } else if (payload.kind === "answer") {
                const peer = peers.get(message.from);
                if (peer) await setRemote(peer, payload.sdp);
            } else if (payload.kind === "ice") {
                const peer = peers.get(message.from) || guestPeer;
                if (peer) await addIce(peer, payload.candidate);
                else earlyIce.push(payload.candidate);
            }
        } catch (error) {
            console.warn("coop video:", error);
        }
    }

    viewer.addEventListener("click", async (event) => {
        const target = event.target.closest("[data-action]");
        if (!target) return;
        const room = state && state.room;
        if (target.dataset.action === "select-all") {
            chosen.clear();
            for (const unit of myUnits) chosen.add(unit.h);
            drawUnits();
        } else if (target.dataset.action === "viewer-leave") {
            if (room) await act({ action: "leave", room: room.id });
            stopVideo();
            render();
        } else if (target.dataset.action === "viewer-retry") {
            guestJoin();
        }
    });

    // The raid ended (or the player left): the video stops.
    function followRaid() {
        const room = state && state.room;
        if (!room || room.status !== "sailing") {
            if (!viewer.hidden || peers.size || guestPeer) stopVideo();
        } else if (!room.is_host && viewer.hidden) {
            guestJoin();
        }
    }

    window.addEventListener("se-live", async (event) => {
        const message = event.detail || {};
        if (message.type === "coop_signal") {
            onSignal(message);
            return;
        }
        if (message.type === "coop_invite") {
            await load();
            showInvites();
            render();
        } else if (message.type === "coop_update") {
            await load();
            render();
            followRaid();
        } else if (message.type === "coop_end") {  // the island ended: everyone's share
            stopVideo();
            await load();
            render();
            const lines = [fill(T.raid_share, { gold: message.gold, xp: message.xp })];
            if (message.prestige) lines.push(fill(T.raid_prestige, { points: message.prestige }));
            showNotice(message.win ? T.raid_won : T.raid_lost, [button(T.close, "notice-close")], lines.join(" "));
        } else if (message.type === "coop_sail") {  // the host set sail: the guests watch the island
            await load();
            render();
            followRaid();
        }
    });

    load().then(() => {
        showInvites();
        render();
        followRaid();  // a guest that reloads its page during a raid watches again
    });
    setInterval(async () => {  // without live notices (duels off), the room still follows
        if (state && (state.room || panelOpen)) {
            await load();
            render();
            followRaid();
        }
    }, 15000);
})();
