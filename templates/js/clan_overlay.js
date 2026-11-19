"use strict";
// In-game clan window (SE_CLANS=on): the game's "Clan" button (swf_clan_button.py) opens a
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

    // SE_CLAN_CREST: the clan's shield built from pieces (the owner's designs of the HUD redesign canvas). Viewbox
    // 0 0 200 240; the division is drawn in the second colour over the first and clipped to the shape; the emblem
    // (viewBox 20 28 60 60) in the middle; a dark and a gold border always, so any mix reads as a clan's shield.
    const CREST_SHAPES = [
        "M16 14H184V108C184 168 144 208 100 228C56 208 16 168 16 108Z", "M18 14H182V172Q182 190 164 190H124L100 228L76 190H36Q18 190 18 172Z",
        "M28 16H172V226L100 190L28 226Z", "M100 22A90 90 0 1 1 99.99 22Z",
        "M100 14C152 14 180 64 180 120C180 176 152 226 100 226C48 226 20 176 20 120C20 64 48 14 100 14Z",
        "M100 10C150 10 180 40 180 80C180 140 130 200 100 232C70 200 20 140 20 80C20 40 50 10 100 10Z", "M18 14H182V130A82 82 0 0 1 18 130Z",
        "M16 30Q60 14 100 30Q140 14 184 30V110C184 168 144 208 100 228C56 208 16 168 16 110Z", "M100 10L184 58V170L100 230L16 170V58Z",
        "M100 10L190 120L100 230L10 120Z", "M30 12H170Q184 12 184 26V214Q184 228 170 228H30Q16 228 16 214V26Q16 12 30 12Z",
        "M16 16H46V36H76V16H124V36H154V16H184V110C184 168 144 208 100 228C56 208 16 168 16 110Z", "M16 14H184V140L100 228L16 140Z",
        "M100 10C150 60 186 110 186 150A86 78 0 0 1 14 150C14 110 50 60 100 10Z",
        "M100 228C40 180 14 140 14 92C14 52 44 24 76 24C88 24 96 30 100 38C104 30 112 24 124 24C156 24 186 52 186 92C186 140 160 180 100 228Z",
        "M66 14H134L186 66V174L134 226H66L14 174V66Z", "M16 70Q100 -10 184 70V120C184 170 144 210 100 228C56 210 16 170 16 120Z",
        "M24 14H176V228L138 196L100 228L62 196L24 228Z", "M16 100A84 84 0 0 1 184 100V200H120L100 228L80 200H16Z",
        "M70 12H130V80H186V140H130V228H70V140H14V80H70Z", "M16 14H70L100 30L130 14H184V110C184 168 144 208 100 228C56 208 16 168 16 110Z",
    ];
    // "" plain; null: a border (bordura) in the second colour.
    const CREST_DIVISIONS = [
        "", "M100 0H200V240H100Z", "M0 110H200V240H0Z", "M100 0H200V110H100ZM0 110H100V240H0Z", "M-10 40L20 10L210 200L180 230Z",
        "M210 40L180 10L-10 200L20 230Z", "M76 0H124V240H76Z", "M0 88H200V136H0Z", "M80 0H120V240H80ZM0 92H200V132H0Z",
        "M-10 30L30 -10L210 170L170 210ZM210 30L170 -10L-10 170L30 210Z", "M0 0H200V70H0Z", "M0 170H200V240H0Z", "M0 0H200L0 240Z",
        "M0 0H200V240Z", "M0 170L100 90L200 170V214L100 134L0 214Z",
        "M50 0h50v48h-50zM150 0h50v48h-50zM0 48h50v48h-50zM100 48h50v48h-50zM50 96h50v48h-50zM150 96h50v48h-50zM0 144h50v48h-50zM100 144h50v48h-50zM50 192h50v48h-50zM150 192h50v48h-50z",
        "M40 0H80V240H40ZM120 0H160V240H120Z", "M0 40H200V76H0ZM0 112H200V148H0ZM0 184H200V220H0Z", null,
        "M60 70H140V120C140 150 120 170 100 180C80 170 60 150 60 120Z", "M30 0H170L100 200Z",
    ];
    // [path, even-odd] in viewBox 20 28 60 60.
    const CREST_EMBLEMS = [
        ["M50 34L56.5 50.5L74 51L60.5 62L65 79L50 69.5L35 79L39.5 62L26 51L43.5 50.5Z", 0], ["M28 72L24 44L38 56L50 38L62 56L76 44L72 72Z M28 76H72V82H28Z", 0],
        ["M32 84V50H36V44H42V50H46V44H54V50H58V44H64V50H68V84Z M45 84V72A5 5 0 0 1 55 72V84Z", 1], ["M58 34A24 24 0 1 0 58 82A18 18 0 1 1 58 34Z", 0],
        ["M50 30C60 44 70 52 66 66C63 78 56 84 50 84C42 84 34 78 34 68C34 58 42 54 44 44C48 52 50 54 52 56C54 48 52 40 50 30Z", 0], ["M56 30L36 62H48L42 86L66 52H54Z", 0],
        ["M48 34H52V70H48Z M38 70H62V75H38Z M47 75H53V84H47Z M50 28L53 34H47Z", 0], ["M48 32H52V86H48Z M52 38C66 38 74 46 74 54C74 62 66 70 52 70Z", 0],
        ["M30 34H66V52H30Z M45 52H51V86H45Z", 0], ["M50 82C34 70 26 60 26 50C26 42 32 36 39 36C44 36 48 39 50 43C52 39 56 36 61 36C68 36 74 42 74 50C74 60 66 70 50 82Z", 0],
        ["M50 30C56 40 58 48 54 58H62C66 52 72 52 74 58C76 66 68 70 62 66H56V72H62V76H54V86H46V76H38V72H44V66H38C32 70 24 66 26 58C28 52 34 52 38 58H46C42 48 44 40 50 30Z", 0],
        ["M50.0 30.0L54.9 39.6L64.0 33.8L63.4 44.6L74.2 44.0L68.4 53.1L78.0 58.0L68.4 62.9L74.2 72.0L63.4 71.4L64.0 82.2L54.9 76.4L50.0 86.0L45.1 76.4L36.0 82.2L36.6 71.4L25.8 72.0L31.6 62.9L22.0 58.0L31.6 53.1L25.8 44.0L36.6 44.6L36.0 33.8L45.1 39.6Z", 0],
        ["M44 32H56V50H74V62H56V86H44V62H26V50H44Z", 0],
        ["M50 28A5 5 0 1 1 49.99 28Z M47 37H53V80H47Z M38 42H62V47H38Z M26 62L34 60Q36 76 50 78Q64 76 66 60L74 62Q72 84 50 86Q28 84 26 62Z", 0],
        ["M50 28L72 56H60L74 74H26L40 56H28Z M46 74H54V86H46Z", 0], ["M20 84L40 50L50 62L62 40L80 84Z", 0],
        ["M22 60Q30 48 38 60Q46 48 54 60Q62 48 70 60Q74 54 78 54V68Q74 68 70 74Q62 62 54 74Q46 62 38 74Q30 62 22 74Z", 0],
        ["M22 58Q50 30 78 58Q50 86 22 58Z M50 46A12 12 0 1 1 49.99 46Z M50 52A6 6 0 1 1 49.99 52Z", 1],
        ["M36 46A12 12 0 1 1 35.99 46Z M36 52A6 6 0 1 1 35.99 52Z M46 55H80V61H74V70H68V61H62V67H56V61H46Z", 1],
        ["M50 32C64 32 74 42 74 54C74 62 70 66 66 68V80H34V68C30 66 26 62 26 54C26 42 36 32 50 32Z M40 47A6 6 0 1 1 39.99 47Z M60 47A6 6 0 1 1 59.99 47Z M46 66L50 59L54 66Z", 1],
        ["M28 84Q30 54 42 34Q38 58 40 84Z M45 84Q46 50 56 30Q52 56 53 84Z M58 84Q62 56 74 40Q66 62 66 84Z", 0], ["M36 40H64L76 54L50 84L24 54Z", 0],
        ["M72 30C50 34 36 50 32 78L36 80C40 68 46 60 54 54C52 52 51 50 51 47C60 45 68 39 72 30Z", 0],
        ["M22 72C28 46 50 32 78 32C72 38 68 42 62 45C70 45 74 47 76 50C68 54 62 56 54 57C60 59 64 61 66 65C56 70 40 72 22 72Z", 0],
        ["M46.4 38.3L46.8 31.2L53.2 31.2L53.6 38.3L61.3 41.5L66.7 36.8L71.2 41.3L66.4 46.6L69.7 54.3L76.8 54.8L76.8 61.2L69.7 61.6L66.5 69.3L71.2 74.7L66.7 79.2L61.4 74.4L53.7 77.7L53.2 84.8L46.8 84.8L46.4 77.7L38.7 74.5L33.3 79.2L28.8 74.7L33.6 69.4L30.3 61.7L23.2 61.2L23.2 54.8L30.3 54.4L33.5 46.7L28.8 41.3L33.3 36.8L38.6 41.6Z M50 50A8 8 0 1 1 49.99 50Z", 1],
    ];
    const CREST_COLORS = ["#b3261e", "#7f1d1d", "#d6457a", "#d9661f", "#f2a516", "#e8b23a", "#f5d547", "#8bc34a", "#2e7d32", "#10835e", "#1b4d2b",
        "#1a9e9e", "#4fa3e0", "#1e4fa3", "#1a2a5e", "#3f3a9e", "#6a2c91", "#9b59b6", "#7a4a22", "#d9c48a", "#e9edf1", "#8a929c", "#4a5560", "#1c1c1c"];
    const CREST_COUNTS = [CREST_SHAPES.length, CREST_DIVISIONS.length, CREST_COLORS.length, CREST_COLORS.length, CREST_EMBLEMS.length, CREST_COLORS.length];
    // A clan without a crest: a plain classic shield in its old emblem's colour with the nearest symbol, in silver.
    const OLD_COLOR_TO_CREST = [1, 14, 9, 17, 5, 12, 19, 16, 3, 8, 23, 1];
    const OLD_SYMBOL_TO_CREST = [7, 2, 1, 3, 5, 4, 15, 6, 10, 13, 23, 12];
    let crestIds = 0;
    let crestShown = false;  // SE_CLAN_CREST: set once the server says so (state.limits.crest)

    function crestParts(clan) {
        const parts = String((clan && clan.crest) || "").split(".").map((part) => parseInt(part, 10));
        if (parts.length === CREST_COUNTS.length && parts.every((n, i) => n >= 1 && n <= CREST_COUNTS[i])) return parts;
        const old = Math.min(Math.max(parseInt(clan && clan.emblem, 10) || 1, 1), OLD_COLOR_TO_CREST.length);
        return [1, 1, OLD_COLOR_TO_CREST[old - 1], 21, OLD_SYMBOL_TO_CREST[old - 1], 21];
    }
    function crestSvg(parts, size) {
        const [shape, division, first, second, emblem, emblemColor] = parts;
        const d = CREST_SHAPES[shape - 1];
        const cut = CREST_DIVISIONS[division - 1];
        const id = "clanx-crest-" + (crestIds += 1);
        const px = size || 56;
        const [symbol, evenOdd] = CREST_EMBLEMS[emblem - 1];
        const field = cut === null
            ? '<path d="' + d + '" fill="none" stroke="' + CREST_COLORS[second - 1] + '" stroke-width="44"/>'
            : cut ? '<path d="' + cut + '" fill="' + CREST_COLORS[second - 1] + '"/>' : "";
        return '<svg class="clanx-emblem clanx-crest" viewBox="0 0 200 240" width="' + px + '" height="' + Math.round(px * 1.2) + '" aria-hidden="true">' +
            '<defs><clipPath id="' + id + '"><path d="' + d + '"/></clipPath></defs><g clip-path="url(#' + id + ')"><rect width="200" height="240" fill="' +
            CREST_COLORS[first - 1] + '"/>' + field + "</g>" +
            '<g transform="translate(45 55) scale(1.833) translate(-20 -28)"><path d="' + symbol + '" fill="' + CREST_COLORS[emblemColor - 1] +
            '" stroke="#1c1c1c" stroke-width="1.6" stroke-linejoin="round"' + (evenOdd ? ' fill-rule="evenodd"' : "") + "/></g>" +
            '<path d="' + d + '" fill="none" stroke="#3a1d08" stroke-width="14" stroke-linejoin="round"/>' +
            '<path d="' + d + '" fill="none" stroke="#e8b23a" stroke-width="7" stroke-linejoin="round"/></svg>';
    }
    // The clan's mark in lists and banners: its crest with SE_CLAN_CREST, else its emblem.
    function clanBadge(clan, size) {
        return crestShown ? crestSvg(crestParts(clan), size) : emblemSvg(clan && clan.emblem, size);
    }
    // The editor: a preview, one tab per piece and that piece's choices (every piece's radios stay in the form).
    function crestEditor(T, clan) {
        const parts = crestParts(clan);
        const labels = [T.crest_shape, T.crest_division, T.crest_color1, T.crest_color2, T.emblem, T.crest_emblem_color];
        let html = '<fieldset class="clanx-crest-editor" data-crest-part="1"><legend>' + esc(T.crest) + '</legend><p class="clanx-muted">' +
            esc(T.crest_hint) + '</p><div class="clanx-crest-layout"><div class="clanx-crest-preview">' + crestSvg(parts, 110) + "</div>" +
            '<div class="clanx-crest-pick"><div class="clanx-crest-tabs" role="tablist">' + labels.map((label, i) =>
                '<button type="button" role="tab" class="clanx-crest-tab" data-crest-tab="' + (i + 1) + '" aria-selected="' + (i === 0) + '">' +
                esc(label) + "</button>").join("") + "</div>";
        for (let part = 1; part <= CREST_COUNTS.length; part += 1) {
            html += '<div class="clanx-crest-options" data-crest-options="' + part + '" role="radiogroup" aria-label="' + esc(labels[part - 1]) + '">';
            for (let n = 1; n <= CREST_COUNTS[part - 1]; n += 1) {
                const color = part === 3 || part === 4 || part === 6;
                const sample = parts.slice();
                sample[part - 1] = n;
                if (part === 1) sample[1] = 1;  // shapes plain, so the outline reads
                html += '<label class="clanx-crest-choice' + (color ? " is-color" : "") + '" title="' + esc(labels[part - 1] + " " + n) + '">' +
                    '<input type="radio" name="crest_' + part + '" value="' + n + '"' + (n === parts[part - 1] ? " checked" : "") + ">" +
                    (color ? '<span class="clanx-swatch" style="background:' + CREST_COLORS[n - 1] + '"></span>' : crestSvg(sample, 34)) + "</label>";
            }
            html += "</div>";
        }
        return html + "</div></div></fieldset>";
    }
    function crestFromForm(form) {
        const parts = [];
        for (let part = 1; part <= CREST_COUNTS.length; part += 1) {
            const checked = form.querySelector('input[name="crest_' + part + '"]:checked');
            parts.push(checked ? checked.value : "1");
        }
        return parts.join(".");
    }

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
        esc, fill, emblemSvg, crestSvg, crestParts, crestEditor,

        tabs(T, state, active) {
            const tabs = state.clan
                ? [["clan", T.tab_clan], ["members", T.tab_members], ["chat", T.tab_chat], ["challenges", T.tab_challenges], ["rivals", T.tab_rivals],
                    ["ranking", T.tab_ranking], ["find", T.tab_find]]
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
            return '<div class="clanx-banner">' + clanBadge(clan, 64) +
                '<div class="clanx-banner-text"><div class="clanx-ribbon">[' + esc(clan.tag) + "] " + esc(clan.name) + "</div>" +
                (clan.description ? '<p class="clanx-motto">« ' + esc(clan.description) + " »</p>" : "") +
                '<p class="clanx-facts"><span>' + esc(fill(T.power, { power: number(clan.power, lang) })) + "</span>" +
                "<span>" + esc(fill(T.members_count, { count: clan.members, max: clan.max })) + "</span>" +
                (T.prestige ? "<span>" + esc(fill(T.prestige, { points: number(clan.prestige || 0, lang) })) + "</span>" : "") +
                "</p></div></div>";
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
            const proposal = state.clan && state.clan.alliance;
            const alliance = proposal && proposal.status === "active" ? proposal : null;
            let html = '<div class="clanx-channels">' +
                '<button type="button" class="clanx-tab' + (channel === "clan" ? " is-active" : "") + '" data-channel="clan">' + esc(T.chat_clan) + "</button>" +
                '<button type="button" class="clanx-tab' + (channel === "alliance" ? " is-active" : "") + '" data-channel="alliance">' +
                esc(T.chat_alliance) + (alliance ? " [" + esc(alliance.ally_tag) + "]" : "") + "</button></div>";
            if (channel === "alliance" && !alliance) {
                // The alliance channel is always offered; without an active alliance it explains how to get one.
                const text = proposal
                    ? '<p>' + esc(fill(T.alliance_chat_pending, { name: "[" + proposal.ally_tag + "] " + proposal.ally_name })) + "</p>"
                    : '<p>' + esc(T.alliance_chat_none) + '</p><p class="clanx-muted">' + esc(T.alliance_chat_how) + "</p>";
                return html + '<div class="clanx-chat clanx-chat-empty">' + text + "</div>";
            }
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
            if (limits.crest) emblems = crestEditor(T, clan) + '<input type="hidden" name="emblem" value="' + esc(clan.emblem || 1) + '">';
            const languages = limits.languages.map((code) => '<option value="' + esc(code) + '"' + (code === clan.language ? " selected" : "") +
                ">" + esc(languageLabel(T, code)) + "</option>").join("");
            return '<form class="clanx-form" data-form="settings">' + (limits.crest ? emblems : "<fieldset><legend>" + esc(T.emblem) + "</legend>" +
                emblems + "</fieldset>") +
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
            if (!c) {
                html += '<p class="clanx-muted">' + esc(T.no_challenge) + "</p><p>" + esc(T.challenge_hint) + "</p>" +
                    '<div class="clanx-actions"><button type="button" class="clanx-btn clanx-btn-green" data-tab="rivals">' + esc(T.tab_rivals) +
                    "</button></div>";
            }
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
                html += '<div class="clanx-actions">' + (duelsUrl ? '<a class="clanx-btn clanx-btn-green" data-in-game="duels" href="' + esc(duelsUrl) + '">' + esc(T.go_duels) + "</a>" : "") +
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

        rivals(T, state, results, query) {
            const clan = state.clan;
            const master = clan.role === "master";
            let html = '<p class="clanx-muted">' + esc(fill(T.rivals_intro, { minutes: state.limits.answer_minutes })) + "</p>";
            if (clan.challenge) {
                html += '<p class="clanx-warn">' + esc(T.rivals_own_busy) + ' <button type="button" class="clanx-linklike" data-tab="challenges">' +
                    esc(T.see_challenges) + "</button></p>";
            } else if (!master) html += '<p class="clanx-warn">' + esc(T.rivals_only_master) + "</p>";
            html += '<form class="clanx-search" data-form="rivals-search"><input name="q" value="' + esc(query || "") + '" placeholder="' +
                esc(T.search_placeholder) + '" maxlength="40" aria-label="' + esc(T.search) + '"><button type="submit" class="clanx-btn clanx-btn-brown">' +
                esc(T.search) + "</button></form>";
            if (!results) return html + '<p class="clanx-muted">' + esc(T.loading) + "</p>";
            const others = results.filter((item) => !item.own && item.id !== clan.id);
            if (!others.length) return html + '<p class="clanx-muted">' + esc(T.no_rivals) + "</p>";
            const canSend = master && !clan.challenge;
            return html + '<ul class="clanx-list">' + others.map((item) => {
                let side = "";
                if (item.allied) side = '<span class="clanx-chip clanx-chip-ally">' + esc(T.allied_label) + "</span>";
                else if (item.busy) side = '<span class="clanx-chip">' + esc(T.rival_busy) + "</span>";
                else if (canSend) {
                    side = '<form class="clanx-inline" data-form="challenge" data-id="' + esc(item.id) + '"><select name="best_of" aria-label="' +
                        esc(T.best_of) + '">' + state.limits.sizes.map((n) => '<option value="' + n + '"' + (n === 5 ? " selected" : "") + ">" +
                        esc(fill(T.duels_count, { count: n })) + "</option>").join("") + '</select><button type="submit" class="clanx-btn clanx-btn-green">' +
                        esc(T.challenge_send) + "</button></form>";
                }
                return '<li><span class="clanx-inline">' + clanBadge(item, 26) + '<button type="button" class="clanx-linklike" data-action="open_clan" data-id="' +
                    esc(item.id) + '"><strong>[' + esc(item.tag) + "] " + esc(item.name) + "</strong></button> <small>" +
                    esc(fill(T.members_count, { count: item.members, max: state.limits.members })) + "</small></span><span>" + side + "</span></li>";
            }).join("") + "</ul>";
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
            return html + '<ul class="clanx-list">' + results.map((clan) => '<li><span class="clanx-inline">' + clanBadge(clan, 26) +
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
            const pieces = limits.crest ? crestEditor(T, { emblem: 1 }) + '<input type="hidden" name="emblem" value="1">'
                : "<fieldset><legend>" + esc(T.emblem) + "</legend>" + emblems + "</div></fieldset>";
            return '<form class="clanx-form" data-form="create">' + pieces +
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
    const CLAN_TABS = ["clan", "members", "chat", "challenges", "rivals"];  // only for players in a clan

    function allianceActive() {
        return Boolean(state && state.clan && state.clan.alliance && state.clan.alliance.status === "active");
    }

    // The "Clan" button lives inside the game (swf_clan_button.py), in its icon panel at the
    // right, once the player is in the empire; the game calls window.seOpenClan() on a click.

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
                const key = form.dataset.form + (form.dataset.id || "") + ":" + field.name;
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
                const key = form.dataset.form + (form.dataset.id || "") + ":" + field.name;
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
        if (!tab || (!state.clan && CLAN_TABS.includes(tab)) || (state.clan && tab === "create")) {
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
        else if (tab === "rivals") body.innerHTML = View.rivals(T, state, results, query);
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
            crestShown = Boolean(state.limits && state.limits.crest);
            if (!tab || (!state.clan && CLAN_TABS.includes(tab)) || (state.clan && tab === "create")) {
                tab = state.clan ? "clan" : "find";
            }
            if ((tab === "find" || tab === "rivals") && results === null) search(query);
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
        if (channel === "alliance" && !allianceActive()) {  // nothing to fetch: the channel explains how to ally
            messages = [];
            if (tab === "chat" && !card) render();
            return;
        }
        try {
            const result = await getJson(config.chat + "?channel=" + encodeURIComponent(channel) + "&after=" + lastMessageId);
            if (!result.ok) {
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
                crestShown = Boolean(state.limits && state.limits.crest);
            }
            if (result.ok) {
                keepForms = false;
                editing = false;
                if (card) card = state.clan && state.clan.id === card.id ? null : await getJson(config.clan + encodeURIComponent(card.id)).catch(() => null);
                if (action === "create" || action === "join") { card = null; tab = "clan"; }
                if (tab === "rivals" && !card) search(query);  // who is busy changed
            }
        } catch (error) {
            showMessage(T.error, false);
        }
        render();
    }

    function askConfirm(text, onYes) {
        showMessage("", true);  // the previous action's message does not belong to this question
        pendingConfirm = onYes;
        confirmBox.querySelector("p").textContent = text;
        confirmBox.querySelector(".clanx-actions").innerHTML = button(T.accept, "confirm_yes", {}, "red") + button(T.cancel, "confirm_no", {}, "brown");
        confirmBox.hidden = false;
    }

    function open() {
        panel.hidden = false;
        showMessage("", true);
        load();
        clearInterval(refreshTimer);
        refreshTimer = setInterval(() => { if (!panel.hidden && !editing && !card && tab !== "create") load(); }, 20000);
        panel.querySelector(".clanx-close").focus();
    }

    function close() {
        panel.hidden = true;
        confirmBox.hidden = true;
        clearInterval(refreshTimer);
        stopChat();
        const game = stage.querySelector("ruffle-player, ruffle-object, ruffle-embed");
        if (game) game.focus();  // back to the game, where the button is
    }

    // Called by the game (ExternalInterface): later, so the game's click handler returns first.
    // The duel script closes the window when the arena opens (it would cover the battle).
    window.seCloseClan = () => { if (!panel.hidden) close(); };
    // seOpenClan() opens or closes the window; seOpenClan("rivals") ("Retar clan") opens it on that tab.
    window.seOpenClan = (wanted) => {
        setTimeout(() => {
            if (!wanted) {
                if (panel.hidden) open(); else close();
                return;
            }
            tab = wanted;
            card = null;
            editing = false;
            stopChat();
            if (tab === "rivals") search(query);
            if (panel.hidden) open(); else load();
        }, 0);
    };
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !panel.hidden) close(); });
    // A hidden tab runs its timers rarely: when the player comes back, show the clan as it is now
    // (removed from the clan, a new challenge, an alliance...).
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible" && !panel.hidden && !editing && tab !== "create") load();
    });
    panel.addEventListener("click", (event) => {
        if (event.target === panel) { close(); return; }
        const tabButton = event.target.closest("[data-tab]");
        if (tabButton) {
            tab = tabButton.dataset.tab;
            card = null;
            editing = false;
            showMessage("", true);
            if (tab === "chat") startChat(); else stopChat();
            if (tab === "find" || tab === "rivals") search(query);
            render();
            load();  // fresh data on every tab change (an alliance or a challenge may have changed meanwhile)
            return;
        }
        const crestTab = event.target.closest("[data-crest-tab]");
        if (crestTab) {
            const editor = crestTab.closest(".clanx-crest-editor");
            editor.dataset.crestPart = crestTab.dataset.crestTab;
            editor.querySelectorAll("[data-crest-tab]").forEach((other) => other.setAttribute("aria-selected", String(other === crestTab)));
            return;
        }
        const channelButton = event.target.closest("[data-channel]");
        if (channelButton) {
            channel = channelButton.dataset.channel;
            startChat();
            return;
        }
        // SE_STAY_IN_GAME: "Go to duels" opens the PvP window's Duels tab instead of the duels page (no reload).
        const inGame = event.target.closest("[data-in-game]");
        if (inGame && document.body.hasAttribute("data-stay-in-game") && typeof window.seOpenPvp === "function") {
            event.preventDefault();
            close();
            window.seOpenPvp(inGame.dataset.inGame);
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
    // SE_CLAN_CREST: the preview and the choices follow each pick (the choices show the shield with it).
    panel.addEventListener("change", (event) => {
        if (!event.target.name || !event.target.name.startsWith("crest_")) return;
        const editor = event.target.closest(".clanx-crest-editor");
        const form = event.target.closest("form");
        if (!editor || !form) return;
        const parts = crestFromForm(form).split(".").map(Number);
        editor.querySelector(".clanx-crest-preview").innerHTML = crestSvg(parts, 110);
        editor.querySelectorAll(".clanx-crest-choice").forEach((choice) => {
            const input = choice.querySelector("input");
            const part = Number(input.name.slice(6));
            if (part === 3 || part === 4 || part === 6) return;
            const sample = parts.slice();
            sample[part - 1] = Number(input.value);
            if (part === 1) sample[1] = 1;
            choice.querySelector("svg").outerHTML = crestSvg(sample, 34);
        });
    });
    panel.addEventListener("submit", (event) => {
        const form = event.target.closest("[data-form]");
        if (!form) return;
        event.preventDefault();
        const fields = Object.fromEntries(new FormData(form).entries());
        if (form.querySelector(".clanx-crest-editor")) {  // SE_CLAN_CREST: the six pieces as one "1.2.14.6.1.21"
            fields.crest = crestFromForm(form);
            for (let part = 1; part <= CREST_COUNTS.length; part += 1) delete fields["crest_" + part];
        }
        if (form.dataset.form === "search" || form.dataset.form === "rivals-search") search(fields.q);
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
