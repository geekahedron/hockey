/* Aggregate and Custom picks omit team and opponent. The page still shows
   the matchup and start from the player on the list, in every picks box. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.join(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const mix = fs.readFileSync(path.join(root, "web", "mix.js"), "utf8");

function grab(name) {
  const mark = "function " + name + "(";
  const start = app.indexOf(mark);
  if (start < 0) throw new Error("missing " + name);
  let i = app.indexOf("{", start);
  let depth = 0;
  for (; i < app.length; i++) {
    if (app[i] === "{") depth++;
    else if (app[i] === "}") {
      depth--;
      if (depth === 0) return app.slice(start, i + 1);
    }
  }
  throw new Error("unclosed " + name);
}

function El(tag) {
  this.tag = tag;
  this.className = "";
  this.textContent = "";
  this.children = [];
  this.style = {};
}
El.prototype.setAttribute = function () {};
El.prototype.addEventListener = function () {};
El.prototype.appendChild = function (kid) {
  this.children.push(kid);
  return kid;
};

const context = {
  document: {
    createElement: function (tag) { return new El(tag); },
    createTextNode: function (text) { return {text: String(text)}; }
  },
  window: {}
};
vm.runInNewContext(mix, context);
const names = [
  "pct", "kindOf", "formatBlock", "torontoGameTime", "pickPids", "playerForPick",
  "gameSource", "startIso", "teamsAndTime", "groupById", "pickTint", "h", "appendChild", "pickRow"
];
vm.runInNewContext(
  names.map(grab).concat([
    "this.teamsAndTime = teamsAndTime;",
    "this.pickRow = pickRow;"
  ]).join("\n"),
  context
);
const M = context.window.HockeyMix;

function assertEqual(actual, expected, label) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a !== b) throw new Error(label + ": " + a + " !== " + b);
}

function metas(node) {
  const lines = [];
  function walk(item) {
    if (!item || typeof item !== "object") return;
    if (item.className === "meta") lines.push(item.textContent || "");
    (item.children || []).forEach(walk);
  }
  walk(node);
  return lines;
}

const earlyStart = "2026-11-18T00:00:00Z";
const lateStart = "2026-11-18T04:30:00Z";
const morning = "2026-11-17T15:00:00Z";
const lateSeen = "2026-11-18T01:00:00Z";
const now = Date.parse("2026-11-18T03:43:00Z");
const methods = [
  {id: "model", label: "Logistic model", kind: "probability"},
  {id: "rate", label: "Scoring-rate estimate", kind: "probability"},
  {id: "goals", label: "Goals per game", kind: "rank"}
];
const selected = {id: "aggregate", label: "Aggregate", kind: "probability"};

function player(pid, name, team, opp, home, start, seen, model, rate) {
  return {
    pid: pid,
    name: name,
    team: team,
    opp: opp,
    home: home,
    start: start,
    first_seen: seen,
    available: true,
    probability: {model: model, rate: rate},
    rank: {goals: 1},
    style: {goals_per_game: 0.4}
  };
}

const early = player(1, "Early", "EDM", "SJS", 1, earlyStart, morning, 0.22, 0.22);
const late = player(2, "Late", "TOR", "CBJ", 0, lateStart, lateSeen, 0.15, 0.55);
const sideA = player(3, "Side Two", "BOS", "PHI", 1, lateStart, morning, 0.2, 0.2);
const sideB = player(4, "Side Three", "VGK", "SEA", 1, lateStart, morning, 0.2, 0.2);
const day = {
  date: "2026-11-17",
  status: "pending",
  phase: "regular",
  generated_at: morning,
  groups: [
    {
      id: 1,
      status: "pending",
      players: [early, late],
      method_picks: {
        model: {pids: [1], name: "Early", team: "EDM", opp: "SJS", home: 1, probability: 0.22},
        rate: {pids: [2], name: "Late", team: "TOR", opp: "CBJ", home: 0, probability: 0.55}
      }
    },
    {id: 2, status: "pending", players: [sideA]},
    {id: 3, status: "pending", players: [sideB]}
  ]
};

const stored = day.groups[0].method_picks.model;
assertEqual(context.teamsAndTime(stored, day.groups[0], day), "EDM vs SJS · 7:00 PM", "stored method pick keeps its own game");

const config = M.aggregateMix(methods);
const aggregate = M.customPick(day, day.groups[0], config, methods, "morning", true, now);
assertEqual(aggregate.name, "Late", "aggregate follows the scoring-rate pick");
assertEqual(aggregate.team, undefined, "aggregate pick drops the team");
assertEqual(aggregate.opp, undefined, "aggregate pick drops the opponent");
assertEqual(context.teamsAndTime(aggregate, day.groups[0], day), "TOR @ CBJ · 11:30 PM", "aggregate game comes from the player");

const custom = M.customPick(day, day.groups[0], M.parseMix("avg"), methods, "morning", true, now);
assertEqual(custom.name, "Late", "custom average uses the player still available");
assertEqual(custom.team, undefined, "custom pick carries no team");
assertEqual(context.teamsAndTime(custom, day.groups[0], day), "TOR @ CBJ · 11:30 PM", "custom game comes from the player");

const suggestions = M.selectionsAt(day, config, methods, now).picks;
const plan = M.dailyPlan(day, config, methods, now);
assertEqual(suggestions[0].name, "Late", "current suggestion");
assertEqual(suggestions[0].team, undefined, "suggestion omits the team");
assertEqual(plan.picks[0].name, "Early", "daily pick locked before the later player");
assertEqual(plan.reason, "game", "locked when the selected game started");
assertEqual(metas(context.pickRow(suggestions, selected, day)), [
  "TOR @ CBJ · 11:30 PM",
  "BOS vs PHI · 11:30 PM",
  "VGK vs SEA · 11:30 PM"
], "current suggestions show the game");
assertEqual(metas(context.pickRow(plan.picks, selected, day)), [
  "EDM vs SJS · 7:00 PM",
  "BOS vs PHI · 11:30 PM",
  "VGK vs SEA · 11:30 PM"
], "daily picks show the game");

const started = player(1, "Early", "EDM", "SJS", 1, earlyStart, morning, 0.22, 0.22);
const doneDay = {
  date: "2026-11-17",
  status: "pending",
  generated_at: morning,
  groups: [
    {id: 1, status: "pending", players: [started]},
    {id: 2, status: "pending", players: [Object.assign({}, sideA, {start: earlyStart})]},
    {id: 3, status: "pending", players: [Object.assign({}, sideB, {start: earlyStart})]}
  ]
};
const donePlan = M.dailyPlan(doneDay, config, methods, now);
assertEqual(metas(context.pickRow(donePlan.picks, selected, doneDay))[0], "EDM vs SJS · 7:00 PM", "all-games-started daily picks keep the game");

const pastPlayer = player(9, "Past", "TBL", "OTT", 0, earlyStart, morning, 0.4, 0.4);
const pastDay = {
  date: "2026-11-16",
  status: "graded",
  generated_at: morning,
  groups: [
    {id: 1, status: "graded", players: [pastPlayer], hit: 0},
    {id: 2, status: "graded", players: [Object.assign({}, sideA, {scored: 0})], hit: 0},
    {id: 3, status: "graded", players: [Object.assign({}, sideB, {scored: 1})], hit: 1}
  ]
};
const pastPlan = M.dailyPlan(pastDay, config, methods, null);
assertEqual(metas(context.pickRow(pastPlan.picks, selected, pastDay))[0], "TBL @ OTT · 7:00 PM", "past daily picks show the game");

["renderTodayPicks", "renderPastPicks"].forEach(function (name) {
  const fn = grab(name);
  const calls = fn.match(/pickRow\([^;]*?\)/g) || [];
  if (!calls.length) throw new Error(name + " does not render a pick row");
  calls.forEach(function (call) {
    if (!/,\s*day\s*\)/.test(call)) throw new Error(name + " omits the day: " + call);
  });
});
const todayFn = grab("renderTodayPicks");
["Current suggestions", "Daily picks", "All games have started."].forEach(function (label) {
  if (todayFn.indexOf(label) < 0) throw new Error("missing view " + label);
});
["teamsAndTime(block, group, day)", "teamsAndTime(pick, group, day)"].forEach(function (needle) {
  if (app.indexOf(needle) < 0) throw new Error("missing " + needle);
});

console.log("pick game ok");
