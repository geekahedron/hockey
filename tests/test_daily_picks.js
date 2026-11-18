/* Daily picks lock once. Current suggestions can keep moving. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "..", "web", "mix.js"), "utf8");
const context = {window: {}};
vm.runInNewContext(src, context);
const M = context.window.HockeyMix;

function assertEqual(actual, expected, label) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a !== b) throw new Error(label + ": " + a + " !== " + b);
}

const methods = [
  {id: "model", label: "Logistic model (player form + matchup)", kind: "probability"}
];
const morning = "2026-11-16T10:00:00-05:00";
const afternoon = "2026-11-16T15:00:00-05:00";
const evening = "2026-11-16T17:30:00-05:00";
const game = "2026-11-16T19:00:00-05:00";

function player(pid, name, prob, scored, seen, extra) {
  const row = {
    pid: pid,
    name: name,
    probability: {model: prob},
    scored: scored,
    first_seen: seen,
    start: game
  };
  Object.keys(extra || {}).forEach(function (key) { row[key] = extra[key]; });
  return row;
}

function day(groups, phase) {
  return {
    date: "2026-11-16",
    status: "graded",
    phase: phase || "regular",
    generated_at: morning,
    groups: groups
  };
}

function group(id, players) {
  return {id: id, status: "graded", players: players, random: 0.25};
}

const early = player(1, "Early", 0.2, 0, morning);
const late = player(2, "Late", 0.9, 1, afternoon);
const sideA = player(3, "SideA", 0.2, 0, morning);
const sideB = player(4, "SideB", 0.2, 0, morning);
const slate = day([
  group(1, [early, late]),
  group(2, [sideA]),
  group(3, [sideB])
]);
const plan = M.dailyPlan(slate, M.configFor("model", null, methods), methods, null);
assertEqual(plan.locked, true, "afternoon threshold locks");
assertEqual(plan.reason, "threshold", "locked because the chance cleared 0.70");
assertEqual(plan.picks[0].name, "Late", "locks the 3 PM pick, not the morning one");
assertEqual(plan.picks[0].hit, 1, "grades the locked player");

const lowMorning = day([
  group(1, [player(1, "Early", 0.2, 1, morning), player(2, "Late", 0.25, 0, evening, {removed_at: null})]),
  group(2, [player(3, "SideA", 0.2, 0, morning)]),
  group(3, [player(4, "SideB", 0.2, 0, morning)])
]);
const waiting = M.dailyPlan(lowMorning, M.configFor("model", null, methods), methods, Date.parse("2026-11-16T16:00:00-05:00"));
assertEqual(waiting.locked, false, "still open before 5 PM when the chance stays low");
assertEqual(waiting.picks[0].name, "Early", "a sub-threshold afternoon list does not replace the morning picks");
const afterFive = M.dailyPlan(lowMorning, M.configFor("model", null, methods), methods, Date.parse("2026-11-16T18:00:00-05:00"));
assertEqual(afterFive.locked, false, "the 5 PM list updates the picks without locking them");
assertEqual(afterFive.picks[0].name, "Late", "5 PM list becomes the daily picks");
const afterGame = M.dailyPlan(lowMorning, M.configFor("model", null, methods), methods, null);
assertEqual(afterGame.locked, true, "first selected game locks them");
assertEqual(afterGame.reason, "game", "locked because a selected game started");
assertEqual(afterGame.picks[0].name, "Late", "the lock keeps the 5 PM pick");

const earlyGame = day([
  group(1, [player(1, "Early", 0.2, 1, morning, {start: "2026-11-16T16:00:00-05:00"})]),
  group(2, [player(3, "SideA", 0.2, 0, morning, {start: "2026-11-16T16:00:00-05:00"})]),
  group(3, [player(4, "SideB", 0.2, 0, morning, {start: "2026-11-16T16:00:00-05:00"})])
]);
const gameLock = M.dailyPlan(earlyGame, M.configFor("model", null, methods), methods, null);
assertEqual(gameLock.reason, "game", "a game before 5 PM locks the morning picks");
assertEqual(gameLock.picks[0].name, "Early", "morning pick is the one that locked");

const playoff = day([
  group(1, [player(1, "Early", 0.2, 1, morning)]),
  group(2, [player(3, "SideA", 0.2, 0, morning)]),
  group(3, [player(4, "SideB", 0.2, 0, morning)])
], "playoffs");
const playoffPlan = M.dailyPlan(playoff, M.aggregateMix(methods), methods, Date.parse(morning));
assertEqual(playoffPlan.locked, true, "playoffs lock immediately");
assertEqual(playoffPlan.reason, "playoffs", "playoff reason");

const strongMorning = day([
  group(1, [
    player(1, "Star", 0.8, 0, morning, {removed_at: afternoon}),
    player(2, "Later", 0.4, 1, afternoon)
  ]),
  group(2, [player(3, "SideA", 0.5, 1, morning)]),
  group(3, [player(4, "SideB", 0.5, 1, morning)])
]);
const storedHits = 1 + 1 + 1;
const locked = M.dailyPlan(strongMorning, M.configFor("model", null, methods), methods, null);
const lockedHits = locked.picks.reduce(function (sum, pick) { return sum + pick.hit; }, 0);
assertEqual(locked.reason, "threshold", "morning chance locks before the later list");
assertEqual(locked.picks[0].name, "Star", "the locked pick is the morning player");
assertEqual(lockedHits, 2, "locked morning slate scores 2");
assertEqual(storedHits, 3, "the final list would have scored 3");

console.log("daily picks ok");
