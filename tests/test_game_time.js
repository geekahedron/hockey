/* Formats the page uses for a player's NHL start, in Toronto time. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");

function grab(name) {
  const mark = "function " + name + "(";
  const start = src.indexOf(mark);
  if (start < 0) throw new Error("missing " + name);
  let i = src.indexOf("{", start);
  let depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error("unclosed " + name);
}

const context = {};
vm.runInNewContext(
  [grab("torontoGameTime"), grab("startIso"), grab("teamsAndTime"), grab("matchup"),
    "this.torontoGameTime = torontoGameTime;",
    "this.teamsAndTime = teamsAndTime;",
    "this.matchup = matchup;"
  ].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
  }
}

// 00:00 UTC on this date is 7:00 PM the previous evening in Toronto (EST).
assertEqual(context.torontoGameTime("2026-11-17T00:00:00Z"), "7:00 PM", "evening");
assertEqual(context.torontoGameTime("2026-11-17T17:00:00Z"), "12:00 PM", "noon");
assertEqual(context.torontoGameTime("2026-11-17T05:00:00Z"), "12:00 AM", "midnight");
assertEqual(context.torontoGameTime(""), "", "blank");
assertEqual(context.torontoGameTime("not-a-time"), "", "bad");

const player = {team: "BOS", opp: "TOR", home: 1, start: "2026-11-17T00:00:00Z"};
assertEqual(context.teamsAndTime(player), "BOS vs TOR · 7:00 PM", "teams");
assertEqual(context.matchup(player), "BOS vs TOR · 7:00 PM · Home", "row");
assertEqual(
  context.matchup({team: "BOS", opp: "TOR", home: 0}),
  "BOS @ TOR · Away",
  "missing start"
);
assertEqual(context.teamsAndTime({team: "BOS"}), "", "no opponent");

const group = {players: [{pid: 9, start: "2026-11-17T00:00:00Z"}]};
const pick = {team: "BOS", opp: "TOR", home: 1, pids: [9]};
assertEqual(context.teamsAndTime(pick, group), "BOS vs TOR · 7:00 PM", "pick looks up start");
assertEqual(context.teamsAndTime({team: "BOS", opp: "TOR", home: 1, pids: [8]}, group), "BOS vs TOR", "unknown pid");
const viaGames = {games: {BOS: "2026-11-17T00:00:00Z"}};
assertEqual(
  context.teamsAndTime({team: "BOS", opp: "TOR", home: 1}, null, viaGames),
  "BOS vs TOR · 7:00 PM",
  "day games map"
);

["teamsAndTime(player, null, day)", "teamsAndTime(block, group, day)", "teamsAndTime(earlier, group, day)", "teamsAndTime(pick, group, day)"].forEach(function (needle) {
  if (!src.includes(needle)) throw new Error("missing " + needle);
});

console.log("game time ok");
