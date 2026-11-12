// Renders every view of the in-game clan window (templates/js/clan_overlay.js) with
// sample states and prints a JSON report. Used by tests/test_clan_overlay_js.py.
"use strict";
const fs = require("fs");
const path = require("path");
const View = require(path.join(__dirname, "..", "templates", "js", "clan_overlay.js"));

// Every text key the server sends (clans_web.overlay_texts), as "[key]" plus the placeholders.
const webSource = fs.readFileSync(path.join(__dirname, "..", "clans_web.py"), "utf8");
const block = webSource.slice(webSource.indexOf("def overlay_texts"), webSource.indexOf("def install_clans"));
const T = {};
for (const match of block.matchAll(/'([\w-]+)': _\(/g)) T[match[1]] = "[" + match[1] + "]{name}{count}{max}{power}{level}{minutes}{needed}{role}{winner}{loser}";

const evil = '<img src=x onerror=alert(1)>';
const limits = { members: 70, assists: 3, name: [3, 24], tag: [2, 5], description: 200, announcement: 500, emblems: 12,
    languages: ["all", "es", "pt-BR", "en"], sizes: [3, 5, 7], answer_minutes: 10 };
function clanState(role) {
    return {
        me: { id: 1, name: "Ana", level: 30, rejoin_minutes: 0, can_create: true, requests: [] },
        limits, ranking: [{ id: 2, tag: "BET", name: evil, won: 2, lost: 1, duel_wins: 5 }], can_challenge: role === "master",
        clan: {
            id: 1, name: evil, tag: "ALF", description: evil, emblem: 5, open: false, min_level: 25, language: "es", members: 3, max: 70,
            announcement: evil + "\nsegunda línea", power: 123456, leader: evil, role, assists: 1,
            members_list: [{ id: 1, name: "Ana", role }, { id: 2, name: evil, role: "assist" }, { id: 3, name: "Caro", role: "member" }],
            requests: role === "member" ? undefined : [{ id: 9, name: evil, when: "hoy" }],
            challenge: { id: 4, status: "active", best_of: 5, incoming: false, rival_id: 2, rival_tag: "BET", rival_name: evil, our_wins: 2,
                their_wins: 1, needed: 3, duel_lines: [{ winner: evil, loser: "Beto", ours: true }] },
            history: [{ id: 3, status: "done", outcome: "won", ending: "majority", rival_tag: "GAM", rival_name: evil, our_wins: 2, their_wins: 0, best_of: 3, when: "ayer" },
                { id: 2, status: "expired", outcome: null, ending: null, rival_tag: "DEL", rival_name: "Delta", best_of: 3, when: "antes" }],
        },
    };
}
const noClan = { me: { id: 7, name: "Eva", level: 10, rejoin_minutes: 0, can_create: true, requests: [] }, limits, ranking: [], clan: null, can_challenge: false };
const card = { id: 2, name: evil, tag: "BET", description: evil, emblem: 3, open: true, min_level: 1, language: "all", members: 4,
    announcement: evil, leader: "Beto", role: null, members_list: [{ id: 5, name: evil, role: "master" }], requested: false, can_challenge_this: true };

const out = {};
for (const role of ["master", "assist", "member"]) {
    const state = clanState(role);
    out[role] = {
        tabs: View.tabs(T, state, "clan"),
        clan: View.clan(T, state, "es", false),
        edit: View.clan(T, state, "es", true),
        members: View.members(T, state),
        challenges: View.challenges(T, state, "/duels"),
        ranking: View.ranking(T, state),
    };
}
const pending = clanState("master");
pending.clan.challenge = { id: 6, status: "pending", best_of: 3, incoming: true, rival_id: 2, rival_tag: "BET", rival_name: "Beta", minutes_left: 7 };
out.pendingIncoming = View.challenges(T, pending, "/duels");
pending.clan.challenge.incoming = false;
out.pendingOutgoing = View.challenges(T, pending, "/duels");
out.noClan = { tabs: View.tabs(T, noClan, "find"), find: View.find(T, noClan, [card], evil), create: View.create(T, noClan),
    findLoading: View.find(T, noClan, null, ""), card: View.clanCard(T, noClan, card, "es"), ranking: View.ranking(T, noClan) };
out.cardForMaster = View.clanCard(T, clanState("master"), card, "en");
const allied = clanState("master");
allied.clan.alliance = { id: 8, status: "active", incoming: false, ally_id: 2, ally_tag: "BET", ally_name: evil };
out.alliedClan = View.clan(T, allied, "es", false);
const chatMessages = [{ id: 1, author: evil, tag: "ALF", text: evil, at: 1700000000, mine: false, can_delete: true },
    { id: 2, author: "Ana", tag: "BET", text: "hola", at: 1700000060, mine: true, can_delete: false }];
out.chatClan = View.chat(T, allied, "clan", chatMessages);
out.chatEmpty = View.chat(T, clanState("member"), "clan", []);
out.chatLoading = View.chat(T, clanState("member"), "clan", null);
const incoming = clanState("master");
incoming.clan.alliance = { id: 9, status: "pending", incoming: true, ally_id: 3, ally_tag: "GAM", ally_name: "Gama" };
out.allianceIncoming = View.clan(T, incoming, "es", false);
incoming.clan.alliance.incoming = false;
out.allianceOutgoing = View.clan(T, incoming, "es", false);
out.allianceMemberView = View.clan(T, Object.assign(clanState("member"), {}), "es", false);
out.cardAlly = View.clanCard(T, clanState("master"), Object.assign({}, card, { can_ally_this: true }), "es");
out.cardAllied = View.clanCard(T, clanState("master"), Object.assign({}, card, { allied_with_me: true, can_challenge_this: true }), "es");
out.emblems = Array.from({ length: 12 }, (_, i) => View.emblemSvg(i + 1, 40));
out.keys = Object.keys(T);
console.log(JSON.stringify(out));
