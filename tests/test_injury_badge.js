/* Injury and returning badges on a player tile. */
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

const names = ["shortDate", "absenceNote", "injuryTitle", "statusBadges"];
const context = {};
vm.runInNewContext(
  names.map(grab).join("\n") + "\n" + names.map(function (name) {
    return "this." + name + " = " + name + ";";
  }).join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
  }
}

assertEqual(context.shortDate("2026-11-02"), "Nov 2", "date");
assertEqual(context.absenceNote({missed_team_games: 7, last_played: "2026-11-02"}), "missed 7 games, last played Nov 2", "note");
assertEqual(context.absenceNote({missed_team_games: 1, last_played: "2026-11-02"}), "missed 1 game, last played Nov 2", "one game");
assertEqual(context.injuryTitle({status: "DTD", detail: "Upper body", updated: "2026-11-15"}), "Upper body · Nov 15", "tooltip");

const both = context.statusBadges({
  injury: {status: "DTD", detail: "Upper body", updated: "2026-11-15"},
  absence: {missed_team_games: 7, last_played: "2026-11-02"}
});
assertEqual(both.length, 2, "both badges");
assertEqual(both[0].label, "DTD", "designation");
assertEqual(both[0].title, "Upper body · Nov 15", "designation tip");
assertEqual(both[1].label, "Returning", "returning");
assertEqual(both[1].title, "missed 7 games, last played Nov 2", "returning tip");

const short = context.statusBadges({absence: {missed_team_games: 2, last_played: "2026-11-14"}});
assertEqual(short.length, 0, "two games is not a badge");

const removed = context.statusBadges({
  available: false,
  injury: {status: "IR", detail: "Knee", updated: "2026-11-11"},
  absence: {missed_team_games: 5, last_played: "2026-11-02"}
});
assertEqual(removed[0].label, "IR", "removed player still badged");
assertEqual(removed[1].label, "Returning", "removed player can be returning");

if (src.indexOf('class: "pill " + badge.kind') < 0) throw new Error("tile badge is missing");
if (src.indexOf("statusBadges(player)") < 0) throw new Error("popup does not list the badges");

console.log("injury badges ok");
