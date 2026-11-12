"use strict";
// In-game clan window (SE_CLANS=on): a "Clan" shield over the game that opens a
// window drawn in the game's style. Every text a player wrote (names, motto,
// announcement) goes through esc() before it reaches the page. Actions are form
// posts with the page's CSRF token; the server checks every permission again.
(function (root) {
    const EMBLEM_COLORS = ["#b3261e", "#1f5fa8", "#2e7d32", "#6a1b9a", "#e08a00", "#00838f",
        "#4e342e", "#283593", "#ad1457", "#558b2f", "#37474f", "#c62828"];
    // Own art: simple symbols on a shield (viewBox 0 0 24 24).
    const EMBLEM_SYMBOLS = [
        "M11 3h2v11h-2zM8 14h8v2H8zM11 16h2v5h-2z",                                     // sword
        "M4 17h16l1-9-5 4-4-6-4 6-5-4zM4 18h16v2H4z",                                     // crown
        "M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z",       // star
        "M6 21V9h2V6h2v3h4V6h2v3h2v12h-4v-4a2 2 0 0 0-4 0v4z",                           // tower
        "M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-3 2-4 2-7 1 1 2 2 2 4 1-2 1-4 1-7z",         // flame
        "M15 3a9 9 0 1 0 6 15A7 7 0 0 1 15 3z",                                           // moon
        "M12 3l6 8h-3l4 5h-6v5h-2v-5H5l4-5H6z",                                           // tree
        "M13 2L5 14h6l-1 8 8-12h-6z",                                                     // bolt
        "M12 21l-8-8a5 5 0 0 1 8-6 5 5 0 0 1 8 6z",                                       // heart
        "M10 3h4v7h7v4h-7v7h-4v-7H3v-4h7z",                                               // cross
        "M5 19C5 10 11 4 20 4c0 9-6 15-15 15z",                                           // leaf
        "M12 2l3 6 6 1-4 5 1 7-6-3-6 3 1-7-4-5 6-1z",                                     // seal
    ];

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
    function emblemSvg(index, size) {
        const n = Math.min(Math.max(parseInt(index, 10) || 1, 1), EMBLEM_SYMBOLS.length);
        const px = size || 56;
        return '<svg class="clanx-emblem" viewBox="0 0 40 46" width="' + px + '" height="' + Math.round(px * 46 / 40) + '" aria-hidden="true">' +
            '<path d="M20 2L37 8v14c0 11-8 19-17 22C11 41 3 33 3 22V8z" fill="' + EMBLEM_COLORS[n - 1] + '" stroke="#3b2410" stroke-width="2"/>' +
            '<path d="M20 5l14 5v12c0 9-6 16-14 19C12 38 6 31 6 22V10z" fill="none" stroke="#f4d77a" stroke-width="1.2" opacity=".85"/>' +
            '<g transform="translate(8 9)"><path d="' + EMBLEM_SYMBOLS[n - 1] + '" fill="#fff6d8"/></g></svg>';
    }
    function button(label, action, data, kind) {
        let attrs = ' data-action="' + esc(action) + '"';
        for (const key of Object.keys(data || {})) attrs += " data-" + key + '="' + esc(data[key]) + '"';
        return '<button type="button" class="clanx-btn' + (kind ? " clanx-btn-" + kind : "") + '"' + attrs + ">" + esc(label) + "</button>";
    }
    function languageLabel(T, code) {
        return T["language_" + code] || T.language_all;
    }

    // ---- views: each returns an HTML string ----
    const View = {
        esc, fill, emblemSvg,

        tabs(T, state, active) {
            const tabs = state.clan
                ? [["clan", T.tab_clan], ["members", T.tab_members], ["chat", T.tab_chat], ["challenges", T.tab_challenges], ["ranking", T.tab_ranking], ["find", T.tab_find]]
                : [["find", T.tab_find], ["create", T.tab_create], ["ranking", T.tab_ranking]];
            return '<div class="clanx-tabs" role="tablist">' + tabs.map(([key, label]) =>
                '<button type="button" role="tab" class="clanx-tab' + (key === active ? " is-active" : "") + '" aria-selected="' +
                (key === active) + '" data-tab="' + key + '">' + esc(label) + "</button>").join("") + "</div>";
        },

        recruitmentChips(T, clan) {
            return '<span class="clanx-chip">' + esc(clan.open ? T.open : T.by_request) + "</span>" +
                '<span class="clanx-chip">' + esc(fill(T.level_min, { level: clan.min_level })) + "</span>" +
                '<span class="clanx-chip">' + esc(languageLabel(T, clan.language)) + "</span>";
        },

        banner(T, clan, lang) {
            return '<div class="clanx-banner">' + emblemSvg(clan.emblem, 64) +
                '<div class="clanx-banner-text"><div class="clanx-ribbon">[' + esc(clan.tag) + "] " + esc(clan.name) + "</div>" +
                (clan.description ? '<p class="clanx-motto">« ' + esc(clan.description) + " »</p>" : "") +
                '<p class="clanx-facts"><span>' + esc(fill(T.power, { power: number(clan.power, lang) })) + "</span>" +
                "<span>" + esc(fill(T.members_count, { count: clan.members, max: clan.max })) + "</span></p></div></div>";
        },

        clan(T, state, lang, editing) {
            const clan = state.clan;
            const limits = state.limits;
            const head = View.banner(T, Object.assign({ max: limits.members }, clan), lang) +
                '<p class="clanx-leader">' + esc(fill(T.leader, { name: clan.leader })) + " · " +
                esc(fill(T.your_rank, { role: T[clan.role] })) + "</p>";
            if (editing && clan.role === "master") return head + View.settingsForm(T, state);
            let html = head + '<div class="clanx-grid"><section class="clanx-card"><h3>' + esc(T.announcement) + "</h3>" +
                (clan.announcement ? '<p class="clanx-announcement">' + esc(clan.announcement).replace(/\n/g, "<br>") + "</p>"
                    : '<p class="clanx-muted">' + esc(T.no_announcement) + "</p>") + "</section>" +
                '<section class="clanx-card"><h3>' + esc(T.challenge_title) + "</h3>" + View.challengeSummary(T, clan) + "</section></div>" +
                '<section class="clanx-card"><h3>' + esc(T.alliance) + "</h3>" + View.alliance(T, clan) + "</section>" +
                '<p class="clanx-recruit"><strong>' + esc(T.recruitment) + ":</strong> " + View.recruitmentChips(T, clan) + "</p>" +
                '<div class="clanx-actions">';
            if (clan.role === "master") {
                html += button(T.edit, "edit", {}, "brown");
                html += button(T.dissolve, "dissolve", {}, "link");
            }
            if (clan.role !== "master" || clan.members === 1) html += button(T.leave, "leave", {}, "link");
            return html + "</div>";
        },

        alliance(T, clan) {
            const a = clan.alliance;
            if (!a) return '<p class="clanx-muted">' + esc(T.no_alliance) + "</p>" + (clan.role === "master" ? '<p class="clanx-muted">' + esc(T.alliance_hint) + "</p>" : "");
            const ally = "[" + a.ally_tag + "] " + a.ally_name;
            let html;
            if (a.status === "active") html = '<p><strong>' + esc(fill(T.ally, { name: ally })) + "</strong></p>";
            else html = "<p>" + esc(fill(a.incoming ? T.alliance_pending_in : T.alliance_pending_out, { name: ally })) + "</p>";
            if (clan.role === "master") {
                html += '<div class="clanx-actions">';
                if (a.status === "active") html += button(T.end_alliance, "end_alliance", { id: a.id }, "red");
                else if (a.incoming) html += button(T.accept_alliance, "accept_alliance", { id: a.id }, "green") + button(T.decline_alliance, "decline_alliance", { id: a.id }, "brown");
                else html += button(T.cancel_alliance, "cancel_alliance", { id: a.id }, "brown");
                html += "</div>";
            }
            return html;
        },

        chat(T, state, channel, messages) {
            const alliance = state.clan && state.clan.alliance && state.clan.alliance.status === "active" ? state.clan.alliance : null;
            let html = '<div class="clanx-channels">' +
                '<button type="button" class="clanx-tab' + (channel === "clan" ? " is-active" : "") + '" data-channel="clan">' + esc(T.chat_clan) + "</button>" +
                (alliance ? '<button type="button" class="clanx-tab' + (channel === "alliance" ? " is-active" : "") + '" data-channel="alliance">' +
                    esc(T.chat_alliance) + " [" + esc(alliance.ally_tag) + "]</button>" : "") + "</div>";
            html += '<div class="clanx-chat" aria-live="polite">';
            if (!messages) html += '<p class="clanx-muted">' + esc(T.loading) + "</p>";
            else if (!messages.length) html += '<p class="clanx-muted">' + esc(T.no_messages) + "</p>";
            else {
                html += messages.map((m) => '<p class="clanx-msg' + (m.mine ? " is-mine" : "") + '"><span class="clanx-msg-head"><strong>' +
                    (m.tag ? "[" + esc(m.tag) + "] " : "") + esc(m.author) + "</strong> <small>" + esc(View.time(m.at)) + "</small>" +
                    "</span>" + esc(m.text) + "</p>").join("");
            }
            html += "</div>";
            return html + '<form class="clanx-search clanx-chat-form" data-form="chat"><input name="text" maxlength="300" autocomplete="off" placeholder="' +
                esc(T.chat_placeholder) + '" aria-label="' + esc(T.chat_placeholder) + '"><button type="submit" class="clanx-btn clanx-btn-green">' +
                esc(T.send) + "</button></form>";
        },

        time(epoch) {
            const date = new Date((Number(epoch) || 0) * 1000);
            return String(date.getHours()).padStart(2, "0") + ":" + String(date.getMinutes()).padStart(2, "0");
        },

        challengeSummary(T, clan) {
            const c = clan.challenge;
            if (!c) return '<p class="clanx-muted">' + esc(T.no_challenge) + "</p>";
            const rival = "[" + c.rival_tag + "] " + c.rival_name;
            if (c.status === "pending") {
                return "<p>" + esc(fill(c.incoming ? T.challenge_incoming : T.challenge_outgoing, { name: rival, count: c.best_of })) + "</p>";
            }
            return "<p>" + esc(fill(T.best_of_against, { count: c.best_of, name: rival })) + '</p><p class="clanx-score">' +
                esc(c.our_wins) + " – " + esc(c.their_wins) + "</p>";
        },

        settingsForm(T, state) {
            const clan = state.clan;
            const limits = state.limits;
            let emblems = '<div class="clanx-emblems" role="radiogroup" aria-label="' + esc(T.emblem) + '">';
            for (let i = 1; i <= limits.emblems; i += 1) {
                emblems += '<label class="clanx-emblem-pick"><input type="radio" name="emblem" value="' + i + '"' +
                    (i === clan.emblem ? " checked" : "") + ">" + emblemSvg(i, 34) + "</label>";
            }
            emblems += "</div>";
            const languages = limits.languages.map((code) => '<option value="' + esc(code) + '"' + (code === clan.language ? " selected" : "") +
                ">" + esc(languageLabel(T, code)) + "</option>").join("");
            return '<form class="clanx-form" data-form="settings"><fieldset><legend>' + esc(T.emblem) + "</legend>" + emblems + "</fieldset>" +
                "<label>" + esc(T.motto) + ' <input name="description" maxlength="' + limits.description + '" value="' + esc(clan.description) + '"></label>' +
                "<label>" + esc(T.announcement) + ' <textarea name="announcement" rows="4" maxlength="' + limits.announcement + '">' +
                esc(clan.announcement) + "</textarea></label>" +
                '<div class="clanx-row"><label>' + esc(T.recruit_mode) + ' <select name="recruit_open"><option value="0"' + (clan.open ? "" : " selected") +
                ">" + esc(T.by_request) + '</option><option value="1"' + (clan.open ? " selected" : "") + ">" + esc(T.open) + "</option></select></label>" +
                "<label>" + esc(T.min_level) + ' <input name="min_level" type="number" min="1" max="99" value="' + esc(clan.min_level) + '"></label>' +
                "<label>" + esc(T.language) + ' <select name="language">' + languages + "</select></label></div>" +
                '<div class="clanx-actions"><button type="submit" class="clanx-btn clanx-btn-green">' + esc(T.save) + "</button>" +
                button(T.cancel, "cancel_edit", {}, "brown") + "</div></form>";
        },

        members(T, state) {
            const clan = state.clan;
            const role = clan.role;
            let html = "";
            if (role === "master" || role === "assist") {
                html += '<section class="clanx-card"><h3>' + esc(T.requests) + "</h3>";
                if (!clan.requests || !clan.requests.length) html += '<p class="clanx-muted">' + esc(T.no_requests) + "</p>";
                else {
                    html += '<ul class="clanx-list">' + clan.requests.map((r) => "<li><span><strong>" + esc(r.name) + '</strong> <small>' + esc(r.when) +
                        "</small></span><span>" + button(T.accept, "accept_request", { id: r.id }, "green") + button(T.reject, "reject_request", { id: r.id }, "brown") +
                        "</span></li>").join("") + "</ul>";
                }
                html += "</section>";
            }
            html += '<ul class="clanx-list">' + clan.members_list.map((m) => {
                const me = m.id === state.me.id;
                let actions = "";
                if (!me && role === "master") {
                    if (m.role === "member" && clan.assists < state.limits.assists) actions += button(T.make_assist, "make_assist", { id: m.id });
                    if (m.role === "assist") actions += button(T.remove_assist, "remove_assist", { id: m.id });
                    actions += button(T.transfer, "transfer", { id: m.id, name: m.name });
                }
                if (!me && (role === "master" || (role === "assist" && m.role === "member"))) actions += button(T.kick, "kick", { id: m.id, name: m.name }, "red");
                return '<li><span><strong>' + esc(m.name) + "</strong>" + (me ? " <small>(" + esc(T.you) + ")</small>" : "") +
                    ' <span class="clanx-role clanx-role-' + esc(m.role) + '">' + esc(T[m.role]) + "</span></span><span>" + actions + "</span></li>";
            }).join("") + "</ul>";
            return html;
        },

        challenges(T, state, duelsUrl) {
            const clan = state.clan;
            const c = clan.challenge;
            let html = '<section class="clanx-card"><h3>' + esc(T.challenge_title) + "</h3>";
            if (!c) html += '<p class="clanx-muted">' + esc(T.no_challenge) + "</p><p>" + esc(T.challenge_hint) + "</p>";
            else if (c.status === "pending") {
                const rival = "[" + c.rival_tag + "] " + c.rival_name;
                html += "<p>" + esc(fill(c.incoming ? T.challenge_incoming : T.challenge_outgoing, { name: rival, count: c.best_of })) + "</p>" +
                    '<p class="clanx-muted">' + esc(fill(T.minutes_left, { minutes: c.minutes_left })) + "</p>";
                if (clan.role === "master") {
                    html += '<div class="clanx-actions">' + (c.incoming
                        ? button(T.accept_challenge, "accept_challenge", { id: c.id }, "green") + button(T.decline_challenge, "decline_challenge", { id: c.id }, "brown")
                        : button(T.cancel_challenge, "cancel_challenge", { id: c.id }, "brown")) + "</div>";
                } else if (c.incoming) html += '<p class="clanx-muted">' + esc(T.only_master_answers) + "</p>";
            } else {
                html += "<p>" + esc(fill(T.best_of_against, { count: c.best_of, name: "[" + c.rival_tag + "] " + c.rival_name })) + "</p>" +
                    '<p class="clanx-score">[' + esc(clan.tag) + "] " + esc(c.our_wins) + " – " + esc(c.their_wins) + " [" + esc(c.rival_tag) + "]</p>" +
                    '<p class="clanx-muted">' + esc(fill(T.needed, { needed: c.needed })) + "</p>";
                if (c.duel_lines && c.duel_lines.length) {
                    html += '<ul class="clanx-list clanx-small">' + c.duel_lines.map((d) => '<li class="' + (d.ours ? "is-won" : "is-lost") + '">' +
                        esc(fill(T.duel_line, { winner: d.winner, loser: d.loser })) + "</li>").join("") + "</ul>";
                }
                html += '<div class="clanx-actions">' + (duelsUrl ? '<a class="clanx-btn clanx-btn-green" href="' + esc(duelsUrl) + '">' + esc(T.go_duels) + "</a>" : "") +
                    (clan.role === "master" ? button(T.surrender, "surrender", { id: c.id }, "red") : "") + "</div>";
            }
            html += "</section>";
            if (clan.history && clan.history.length) {
                const endings = { majority: T.by_majority, surrender: T.by_surrender, dissolved: T.by_dissolved };
                html += '<section class="clanx-card"><h3>' + esc(T.history) + '</h3><ul class="clanx-list clanx-small">' + clan.history.map((h) => {
                    const label = h.outcome ? T[h.outcome] : (T[h.status] || h.status);
                    return '<li class="' + (h.outcome === "won" ? "is-won" : h.outcome === "lost" ? "is-lost" : "") + '"><span><strong>' + esc(label) +
                        "</strong> · [" + esc(h.rival_tag) + "] " + esc(h.rival_name) + (h.outcome ? " · " + esc(h.our_wins) + "–" + esc(h.their_wins) +
                        " " + esc(endings[h.ending] || "") : "") + "</span><small>" + esc(h.when) + "</small></li>";
                }).join("") + "</ul></section>";
            }
            return html;
        },

        ranking(T, state) {
            if (!state.ranking || !state.ranking.length) return '<p class="clanx-muted">' + esc(T.no_ranking) + "</p>";
            return '<table class="clanx-table"><thead><tr><th>#</th><th>' + esc(T.tab_clan) + "</th><th>" + esc(T.challenges_won) + "</th><th>" +
                esc(T.challenges_lost) + "</th><th>" + esc(T.duels_won) + "</th></tr></thead><tbody>" + state.ranking.map((row, i) =>
                "<tr><td>" + (i + 1) + '</td><td><button type="button" class="clanx-linklike" data-action="open_clan" data-id="' + esc(row.id) + '">[' +
                esc(row.tag) + "] " + esc(row.name) + "</button></td><td>" + esc(row.won) + "</td><td>" + esc(row.lost) + "</td><td>" + esc(row.duel_wins) +
                "</td></tr>").join("") + "</tbody></table>";
        },

        find(T, state, results, query) {
            let html = '<form class="clanx-search" data-form="search"><input name="q" value="' + esc(query || "") + '" placeholder="' + esc(T.search_placeholder) +
                '" maxlength="40" aria-label="' + esc(T.search) + '"><button type="submit" class="clanx-btn clanx-btn-brown">' + esc(T.search) + "</button></form>";
            if (!state.clan) {
                html += '<p class="clanx-muted">' + esc(T.no_clan) + "</p>";
                if (state.me.rejoin_minutes) html += '<p class="clanx-warn">' + esc(fill(T.rejoin_wait, { minutes: state.me.rejoin_minutes })) + "</p>";
            }
            if (!results) return html + '<p class="clanx-muted">' + esc(T.loading) + "</p>";
            if (!results.length) return html + '<p class="clanx-muted">' + esc(T.no_clans) + "</p>";
            return html + '<ul class="clanx-list">' + results.map((clan) => '<li><span class="clanx-inline">' + emblemSvg(clan.emblem, 26) +
                "<strong>[" + esc(clan.tag) + "] " + esc(clan.name) + "</strong> <small>" + esc(fill(T.members_count, { count: clan.members, max: state.limits.members })) +
                "</small></span><span>" + View.recruitmentChips(T, clan) + button(T.view, "open_clan", { id: clan.id }, "brown") + "</span></li>").join("") + "</ul>";
        },

        create(T, state) {
            const limits = state.limits;
            if (state.me.rejoin_minutes) return '<p class="clanx-warn">' + esc(fill(T.rejoin_wait, { minutes: state.me.rejoin_minutes })) + "</p>";
            if (!state.me.can_create) return '<p class="clanx-warn">' + esc(T.create_tutorial) + "</p>";
            let emblems = '<div class="clanx-emblems" role="radiogroup" aria-label="' + esc(T.emblem) + '">';
            for (let i = 1; i <= limits.emblems; i += 1) {
                emblems += '<label class="clanx-emblem-pick"><input type="radio" name="emblem" value="' + i + '"' + (i === 1 ? " checked" : "") + ">" +
                    emblemSvg(i, 34) + "</label>";
            }
            return '<form class="clanx-form" data-form="create"><fieldset><legend>' + esc(T.emblem) + "</legend>" + emblems + "</div></fieldset>" +
                '<div class="clanx-row"><label>' + esc(T.name) + ' <input name="name" required minlength="' + limits.name[0] + '" maxlength="' + limits.name[1] +
                '"></label><label>' + esc(T.tag) + ' <input name="tag" required minlength="' + limits.tag[0] + '" maxlength="' + limits.tag[1] +
                '" pattern="[A-Za-z0-9]+" class="clanx-upper"></label></div><label>' + esc(T.motto) + ' <input name="description" maxlength="' +
                limits.description + '"></label><div class="clanx-actions"><button type="submit" class="clanx-btn clanx-btn-green">' + esc(T.create) +
                "</button></div></form>";
        },

        clanCard(T, state, detail, lang) {
            let html = '<div class="clanx-actions clanx-top">' + button(T.back, "back", {}, "brown") + "</div>" +
                View.banner(T, Object.assign({ max: state.limits.members }, detail), lang) +
                '<p class="clanx-leader">' + esc(fill(T.leader, { name: detail.leader })) + "</p>" +
                '<p class="clanx-recruit"><strong>' + esc(T.recruitment) + ":</strong> " + View.recruitmentChips(T, detail) + "</p>";
            if (detail.announcement) html += '<section class="clanx-card"><h3>' + esc(T.announcement) + '</h3><p class="clanx-announcement">' +
                esc(detail.announcement).replace(/\n/g, "<br>") + "</p></section>";
            if (!state.clan && !detail.role) {
                html += '<div class="clanx-actions">';
                if (detail.requested) html += '<span class="clanx-chip">' + esc(T.requested) + "</span>" + button(T.cancel_request, "cancel_request", { id: detail.id }, "brown");
                else if (!state.me.rejoin_minutes && detail.members < state.limits.members) {
                    html += button(detail.open ? T.join : T.ask, "join", { id: detail.id }, "green");
                }
                html += "</div>";
            }
            if (detail.allied_with_me) html += '<p><span class="clanx-chip clanx-chip-ally">' + esc(T.allied_label) + "</span></p>";
            else if (detail.alliance && detail.alliance.status === "active") {
                html += '<p class="clanx-muted">' + esc(fill(T.ally, { name: "[" + detail.alliance.ally_tag + "] " + detail.alliance.ally_name })) + "</p>";
            }
            if (detail.can_ally_this) html += '<div class="clanx-actions">' + button(T.propose_alliance, "propose_alliance", { id: detail.id }, "brown") + "</div>";
            if (detail.can_challenge_this && !detail.allied_with_me) {
                html += '<section class="clanx-card"><h3>' + esc(T.challenge_clan) + '</h3><form class="clanx-row" data-form="challenge" data-id="' + esc(detail.id) +
                    '"><label>' + esc(T.best_of) + ' <select name="best_of">' + state.limits.sizes.map((n) => '<option value="' + n + '"' + (n === 5 ? " selected" : "") +
                    ">" + esc(fill(T.duels_count, { count: n })) + "</option>").join("") + '</select></label><button type="submit" class="clanx-btn clanx-btn-green">' +
                    esc(T.challenge_send) + '</button></form><p class="clanx-muted">' + esc(fill(T.answer_minutes, { minutes: state.limits.answer_minutes })) + "</p></section>";
            }
            html += '<ul class="clanx-list clanx-small">' + detail.members_list.map((m) => "<li><span>" + esc(m.name) + ' <span class="clanx-role clanx-role-' +
                esc(m.role) + '">' + esc(T[m.role]) + "</span></span></li>").join("") + "</ul>";
            return html;
        },
    };

    root.ClanOverlayView = View;
    if (typeof module !== "undefined" && module.exports) module.exports = View;

    // ---- controller (browser only) ----
    if (typeof document === "undefined") return;
    const configElement = document.getElementById("clan-overlay-config");
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const T = config.texts;
    const lang = document.documentElement.lang || "es";
    const stage = document.querySelector(".game-stage") || document.body;
    let state = null;
    let tab = null;
    let editing = false;
    let results = null;
    let query = "";
    let card = null;
    let pendingConfirm = null;
    let refreshTimer = null;
    let channel = "clan";
    let messages = null;
    let chatTimer = null;
    let lastMessageId = 0;

    const shield = document.createElement("button");
    shield.type = "button";
    shield.className = "clanx-shield";
    shield.setAttribute("aria-haspopup", "dialog");
    shield.innerHTML = emblemSvg(3, 40) + '<span class="clanx-shield-label">' + esc(T.button) + "</span>";
    stage.appendChild(shield);

    const panel = document.createElement("div");
    panel.className = "clanx-overlay";
    panel.hidden = true;
    panel.innerHTML = '<div class="clanx-window" role="dialog" aria-modal="true" aria-labelledby="clanx-title">' +
        '<div class="clanx-titlebar"><h2 id="clanx-title">' + esc(T.title) + '</h2><button type="button" class="clanx-close" data-action="close" aria-label="' +
        esc(T.close) + '">×</button></div><div class="clanx-tabsbar"></div><div class="clanx-message" role="status" aria-live="polite" hidden></div>' +
        '<div class="clanx-confirm" hidden><p></p><div class="clanx-actions"></div></div><div class="clanx-body"></div></div>';
    stage.appendChild(panel);
    const tabsBar = panel.querySelector(".clanx-tabsbar");
    const body = panel.querySelector(".clanx-body");
    const messageBox = panel.querySelector(".clanx-message");
    const confirmBox = panel.querySelector(".clanx-confirm");

    function showMessage(text, ok) {
        messageBox.textContent = text || "";
        messageBox.className = "clanx-message " + (ok ? "is-ok" : "is-error");
        messageBox.hidden = !text;
    }

    // The window redraws itself (periodic refresh, fresh data on every tab change):
    // whatever the player is typing in a form must survive the redraw.
    function snapshotForms() {
        const values = {};
        let focus = null;
        body.querySelectorAll("[data-form]").forEach((form) => {
            for (const field of form.elements) {
                if (!field.name) continue;
                const key = form.dataset.form + ":" + field.name;
                if (field.type === "radio" || field.type === "checkbox") {
                    if (field.checked) values[key] = field.value;
                } else {
                    values[key] = field.value;
                }
                if (field === document.activeElement) {
                    focus = { key, start: field.selectionStart, end: field.selectionEnd };
                }
            }
        });
        return { values, focus };
    }

    function restoreForms(snapshot) {
        body.querySelectorAll("[data-form]").forEach((form) => {
            for (const field of form.elements) {
                const key = form.dataset.form + ":" + field.name;
                if (!field.name || !(key in snapshot.values)) continue;
                if (field.type === "radio" || field.type === "checkbox") field.checked = field.value === snapshot.values[key];
                else field.value = snapshot.values[key];
                if (snapshot.focus && snapshot.focus.key === key) {
                    field.focus();
                    try { field.setSelectionRange(snapshot.focus.start, snapshot.focus.end); } catch (error) { /* not a text field */ }
                }
            }
        });
    }

    let keepForms = true;  // false right after an action succeeded: its form starts empty again

    function render() {
        const snapshot = keepForms ? snapshotForms() : { values: {}, focus: null };
        keepForms = true;
        draw();
        restoreForms(snapshot);
    }

    function draw() {
        if (!state) {
            body.innerHTML = '<p class="clanx-muted">' + esc(T.loading) + "</p>";
            return;
        }
        if (!tab || (!state.clan && ["clan", "members", "challenges"].includes(tab)) || (state.clan && tab === "create")) {
            tab = state.clan ? "clan" : "find";
        }
        tabsBar.innerHTML = View.tabs(T, state, card ? null : tab);
        if (card) body.innerHTML = View.clanCard(T, state, card, lang);
        else if (tab === "clan") body.innerHTML = View.clan(T, state, lang, editing);
        else if (tab === "members") body.innerHTML = View.members(T, state);
        else if (tab === "chat") {
            body.innerHTML = View.chat(T, state, channel, messages);
            const list = body.querySelector(".clanx-chat");
            list.scrollTop = list.scrollHeight;
        }
        else if (tab === "challenges") body.innerHTML = View.challenges(T, state, config.duels);
        else if (tab === "ranking") body.innerHTML = View.ranking(T, state);
        else if (tab === "find") body.innerHTML = View.find(T, state, results, query);
        else if (tab === "create") body.innerHTML = View.create(T, state);
    }

    async function getJson(url) {
        const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
    }

    async function load() {
        try {
            state = await getJson(config.state);
            if (state.clan) state.clan.max = state.limits.members;
            if (!tab || (!state.clan && ["clan", "members", "challenges"].includes(tab)) || (state.clan && tab === "create")) {
                tab = state.clan ? "clan" : "find";
            }
            if (tab === "find" && results === null) search(query);
        } catch (error) {
            showMessage(T.error, false);
        }
        render();
    }

    async function search(text) {
        query = text || "";
        results = null;
        render();
        try {
            results = (await getJson(config.search + "?q=" + encodeURIComponent(query))).clans;
        } catch (error) {
            results = [];
            showMessage(T.error, false);
        }
        render();
    }

    async function openClan(id) {
        try {
            card = await getJson(config.clan + encodeURIComponent(id));
        } catch (error) {
            showMessage(T.error, false);
        }
        render();
    }

    async function loadChat(reset) {
        if (reset) { messages = null; lastMessageId = 0; render(); }
        try {
            const result = await getJson(config.chat + "?channel=" + encodeURIComponent(channel) + "&after=" + lastMessageId);
            if (!result.ok) {
                if (channel !== "clan") { channel = "clan"; return loadChat(true); }
                messages = [];
            } else {
                messages = (reset || !messages) ? result.messages : messages.concat(result.messages).slice(-200);
            }
            if (messages.length) lastMessageId = messages[messages.length - 1].id;
        } catch (error) {
            if (!messages) messages = [];
        }
        if (tab === "chat" && !card) render();
    }

    function startChat() {
        clearInterval(chatTimer);
        loadChat(true);
        chatTimer = setInterval(() => { if (!panel.hidden && tab === "chat" && !card) loadChat(false); }, 3000);
    }

    function stopChat() {
        clearInterval(chatTimer);
        chatTimer = null;
    }

    async function act(action, fields) {
        const data = new FormData();
        data.append("csrf_token", config.csrf);
        data.append("action", action);
        for (const [key, value] of Object.entries(fields || {})) data.append(key, value);
        try {
            const response = await fetch(config.action, { method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" } });
            const result = await response.json();
            if (action === "post_message") {
                if (!result.ok) showMessage(result.message, false);
                else showMessage("", true);
                await loadChat(false);
                return result.ok;
            }
            showMessage(result.message, result.ok);
            if (result.state) {
                state = result.state;
                if (state.clan) state.clan.max = state.limits.members;
            }
            if (result.ok) {
                keepForms = false;
                editing = false;
                if (card) card = state.clan && state.clan.id === card.id ? null : await getJson(config.clan + encodeURIComponent(card.id)).catch(() => null);
                if (action === "create" || action === "join") { card = null; tab = "clan"; }
            }
        } catch (error) {
            showMessage(T.error, false);
        }
        render();
    }

    function askConfirm(text, onYes) {
        pendingConfirm = onYes;
        confirmBox.querySelector("p").textContent = text;
        confirmBox.querySelector(".clanx-actions").innerHTML = button(T.accept, "confirm_yes", {}, "red") + button(T.cancel, "confirm_no", {}, "brown");
        confirmBox.hidden = false;
    }

    function open() {
        panel.hidden = false;
        shield.setAttribute("aria-expanded", "true");
        showMessage("", true);
        load();
        clearInterval(refreshTimer);
        refreshTimer = setInterval(() => { if (!panel.hidden && !editing && !card && tab !== "create") load(); }, 20000);
        panel.querySelector(".clanx-close").focus();
    }

    function close() {
        panel.hidden = true;
        shield.setAttribute("aria-expanded", "false");
        confirmBox.hidden = true;
        clearInterval(refreshTimer);
        stopChat();
        shield.focus();
    }

    shield.addEventListener("click", () => (panel.hidden ? open() : close()));
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !panel.hidden) close(); });
    panel.addEventListener("click", (event) => {
        if (event.target === panel) { close(); return; }
        const tabButton = event.target.closest("[data-tab]");
        if (tabButton) {
            tab = tabButton.dataset.tab;
            card = null;
            editing = false;
            showMessage("", true);
            if (tab === "chat") startChat(); else stopChat();
            if (tab === "find") search(query);
            render();
            load();  // fresh data on every tab change (an alliance or a challenge may have changed meanwhile)
            return;
        }
        const channelButton = event.target.closest("[data-channel]");
        if (channelButton) {
            channel = channelButton.dataset.channel;
            startChat();
            return;
        }
        const target = event.target.closest("[data-action]");
        if (!target) return;
        const { action, id, name } = target.dataset;
        const simple = { accept_request: "request_id", reject_request: "request_id", make_assist: "target_id", remove_assist: "target_id",
            propose_alliance: "clan_id", accept_alliance: "alliance_id", decline_alliance: "alliance_id",
            cancel_alliance: "alliance_id",
            accept_challenge: "challenge_id", decline_challenge: "challenge_id", cancel_challenge: "challenge_id", cancel_request: "clan_id", join: "clan_id" };
        if (action === "close") close();
        else if (action === "confirm_yes") { confirmBox.hidden = true; const run = pendingConfirm; pendingConfirm = null; if (run) run(); }
        else if (action === "confirm_no") { confirmBox.hidden = true; pendingConfirm = null; }
        else if (action === "edit") { editing = true; showMessage("", true); render(); }
        else if (action === "cancel_edit") { editing = false; render(); }
        else if (action === "open_clan") openClan(id);
        else if (action === "back") { card = null; render(); }
        else if (action === "kick") askConfirm(fill(T.kick_confirm, { name }), () => act("kick", { target_id: id }));
        else if (action === "transfer") askConfirm(fill(T.transfer_confirm, { name }), () => act("transfer", { target_id: id }));
        else if (action === "surrender") askConfirm(T.surrender_confirm, () => act("surrender", { challenge_id: id }));
        else if (action === "leave") askConfirm(T.leave_confirm, () => act("leave"));
        else if (action === "end_alliance") askConfirm(T.end_alliance_confirm, () => act("end_alliance", { alliance_id: id }));
        else if (action === "cancel_alliance") act("end_alliance", { alliance_id: id });
        else if (action === "dissolve") askConfirm(T.dissolve_confirm, () => act("dissolve", { confirm: "yes" }));
        else if (simple[action]) act(action, { [simple[action]]: id });
    });
    panel.addEventListener("submit", (event) => {
        const form = event.target.closest("[data-form]");
        if (!form) return;
        event.preventDefault();
        const fields = Object.fromEntries(new FormData(form).entries());
        if (form.dataset.form === "search") search(fields.q);
        else if (form.dataset.form === "create") act("create", fields);
        else if (form.dataset.form === "settings") act("settings", fields);
        else if (form.dataset.form === "challenge") act("challenge", { clan_id: form.dataset.id, best_of: fields.best_of });
        else if (form.dataset.form === "chat" && fields.text && fields.text.trim()) {
            act("post_message", { channel, text: fields.text }).then((ok) => {
                const input = body.querySelector('[data-form="chat"] input');
                if (ok && input) { input.value = ""; input.focus(); }
            });
        }
    });
})(typeof window !== "undefined" ? window : globalThis);
