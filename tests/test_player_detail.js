/* Position label and the calculation-input dialog rows. */
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

const names = [
  "positionLabel", "formatInput", "slateRows", "slateNote",
  "detailMethods", "inputSections"
];
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

assertEqual(context.positionLabel("C"), "C", "center");
assertEqual(context.positionLabel("L"), "LW", "left");
assertEqual(context.positionLabel("LW"), "LW", "left wing");
assertEqual(context.positionLabel("R"), "RW", "right");
assertEqual(context.positionLabel("rw"), "RW", "right wing");
assertEqual(context.positionLabel("D"), "D", "defense");
assertEqual(context.positionLabel("LD"), "D", "left defense");
assertEqual(context.positionLabel(""), "", "blank");
assertEqual(context.formatInput(null), "not recorded", "missing number");
assertEqual(context.formatInput(3), "3", "whole number");
assertEqual(context.formatInput(0.25), "0.25", "fraction");

const methods = [
  {id: "model", label: "Logistic model (player form + matchup)", kind: "probability"},
  {id: "rate", label: "Scoring-rate estimate", kind: "probability"},
  {id: "goals", label: "Goals per game", kind: "rank"}
];

function valueOf(rows, label) {
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].label === label) return rows[i].value;
  }
  throw new Error("missing row " + label);
}

const removed = {
  name: "Gone",
  position: "L",
  available: false,
  home: 0,
  probability: {model: 0.182, rate: 0.25},
  rank: {goals: 2},
  style: {
    gp: 10, goals: 4, goals_per_game: 0.4, shots: 20, shots_per_game: 2,
    shooting_pct: 20, toi_per_game: 16.5, pp_toi_per_game: 2.25,
    opp_ga_per_game: 3.1, home_away: "AWAY"
  },
  inputs: {
    model: {home: 0, cur_gp: 10, p_base: 0.12, log_g60: -1.5, log1p_cur_gp: 2.4},
    estimate: {cur_gp: 10, cur_g: 4, cur_sog: 20, cur_toi: 165, prev_gp: 40, opp_ga_pg: 3.1, rest_t: 1, is_d: 0}
  }
};

const slate = context.slateRows(removed);
assertEqual(valueOf(slate, "Pos"), "LW", "position");
assertEqual(valueOf(slate, "GP"), "10", "games");
assertEqual(valueOf(slate, "G"), "4", "goals");
assertEqual(valueOf(slate, "Shots/GP"), "2.00", "shots");
assertEqual(valueOf(slate, "Shoot%"), "20.0%", "shooting");
assertEqual(valueOf(slate, "PP TOI/GP"), "2.25", "power play");
assertEqual(valueOf(slate, "TOI/GP"), "16.50", "ice time");
assertEqual(valueOf(slate, "Goals/GP"), "0.40", "rate");
assertEqual(valueOf(slate, "EV line"), "not recorded", "even strength line");
assertEqual(valueOf(slate, "PP line"), "not recorded", "power play line");
assertEqual(valueOf(slate, "Home/Away"), "Away", "away");
assertEqual(valueOf(slate, "Opponent GAA"), "3.10", "opponent");
assertEqual(
  context.slateNote(slate),
  "Even-strength line and power-play line are not inputs to these calculations and are not recorded.",
  "line note"
);

const empty = context.slateRows({name: "New"});
assertEqual(valueOf(empty, "Pos"), "not recorded", "missing position");
assertEqual(valueOf(empty, "GP"), "not recorded", "missing games");
assertEqual(valueOf(empty, "EV line"), "not recorded", "missing line");

const sections = context.inputSections(removed, methods);
assertEqual(sections.length, 3, "three methods");
assertEqual(sections[0].title, "Logistic model (player form + matchup)", "model title");
assertEqual(sections[0].result, "18.2%", "model probability");
assertEqual(valueOf(sections[0].rows, "Poisson baseline probability"), "0.12", "baseline");
assertEqual(valueOf(sections[0].rows, "Log of shrunk goals per 60"), "-1.5", "log goals");
assertEqual(valueOf(sections[0].rows, "Shrunk shots per 60 minutes"), "not recorded", "missing rate");
assertEqual(sections[1].title, "Scoring-rate estimate", "estimate title");
assertEqual(sections[1].result, "25.0%", "estimate probability");
assertEqual(sections[1].rows.some(function (row) { return row.label === "Age"; }), false, "blank age is hidden");
assertEqual(sections[1].rows.some(function (row) { return row.label === "Individual expected goals"; }), false, "blank expected goals are hidden");
assertEqual(valueOf(sections[1].rows, "Games"), "10", "this season games");
assertEqual(valueOf(sections[1].rows, "Rest days (1 means played yesterday)"), "1", "rest");
assertEqual(sections[2].title, "Goals per game", "rank title");
assertEqual(sections[2].resultLabel, null, "rank is not a probability");
assertEqual(valueOf(sections[2].rows, "Rank in this group"), "#2", "rank");
assertEqual(valueOf(sections[2].rows, "Goals per game"), "0.40", "goals per game");
if (sections[2].note.indexOf("does not compute a probability") < 0) {
  throw new Error("rank note should say it is not a probability");
}

const blank = context.inputSections({}, methods);
assertEqual(blank[0].result, "not recorded", "missing model probability");
assertEqual(blank[1].rows.some(function (row) { return row.label === "Age"; }), false, "age without a row");
var withAge = context.inputSections({
  inputs: {estimate: {age: 27, cur_gp: 10}}
}, methods);
assertEqual(valueOf(withAge[1].rows, "Age"), "27", "stored age is shown");
assertEqual(blank[2].result, null, "goals per game has no probability");

if (src.indexOf('event.target === dialog') < 0) throw new Error("backdrop click is missing");
if (src.indexOf('event.key !== "Escape"') < 0) throw new Error("escape close is missing");
if (src.indexOf('event.key !== "Enter" && event.key !== " "') < 0) throw new Error("keyboard open is missing");
if (src.indexOf('id="player-detail"') >= 0) throw new Error("dialog markup belongs in the page, not the script");
if (src.indexOf("showModal") < 0) throw new Error("dialog open is missing");
if (src.indexOf('role: "button"') < 0) throw new Error("tile is not a button");
if (src.indexOf('aria-haspopup') < 0) throw new Error("tile does not announce a dialog");
if (src.indexOf("not recorded") < 0) throw new Error("missing inputs need the recorded phrase");

console.log("player detail ok");
