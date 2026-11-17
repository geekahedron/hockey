/* Custom mix selection and the record counters. */
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
  {id: "model", label: "Logistic model (player form + matchup)", kind: "probability"},
  {id: "rate", label: "Scoring-rate estimate", kind: "probability"},
  {id: "goals", label: "Goals per game", kind: "rank"}
];

assertEqual(M.parseMix(""), M.defaultMix(), "empty config");
assertEqual(M.parseMix("avg").preset, "average", "average preset");
assertEqual(M.serializeMix(M.parseMix("avg")), "avg", "average round trip");
const lists = M.parseMix("1=model|2=rate|3=goals|m10=goals|fr=model|fp=goals");
assertEqual(lists.lists["2"], "rate", "list 2");
assertEqual(lists.months["10"], "goals", "october");
assertEqual(lists.phases.playoffs, "goals", "playoffs");
assertEqual(M.serializeMix(lists), "2=rate|3=goals|m10=goals|fr=model|fp=goals", "serialize");
const byList = M.parseMix("2=rate|m10=goals");
assertEqual(M.methodForList(byList, 2, "2025-11-03", "regular"), "rate", "november uses the list");
assertEqual(M.methodForList(byList, 2, "2025-10-03", "regular"), "goals", "october override");
assertEqual(M.methodForList(lists, 2, "2025-10-03", "playoffs"), "goals", "phase beats month");
assertEqual(M.methodForList(lists, 2, "2025-10-03", "regular"), "model", "regular phase beats october");
assertEqual(M.phaseOf({}), "regular", "missing phase");
assertEqual(M.phaseOf({phase: "playoff"}), "playoffs", "playoff alias");

const players = [
  {pid: 1, name: "A", available: true, scored: 1, probability: {model: 0.2, rate: 0.4}},
  {pid: 2, name: "B", available: true, scored: 0, probability: {model: 0.5, rate: 0.1}}
];
const day = {
  date: "2025-11-02",
  status: "graded",
  phase: "regular",
  groups: [{
    id: 1,
    status: "graded",
    hit: 0,
    pick: {pids: [2], name: "B", probability: 0.5, hit: 0},
    method_picks: {
      model: {pids: [2], name: "B", probability: 0.5, hit: 0},
      rate: {pids: [1], name: "A", probability: 0.4, hit: 1},
      goals: {pids: [1], name: "A", hit: 1, rank: 1, goals_per_game: 0.4}
    },
    players: players,
    full_day: {
      hit: 1,
      pick: {pids: [1], name: "A", probability: 0.2, hit: 1},
      method_picks: {
        model: {pids: [1], name: "A", probability: 0.2, hit: 1}
      }
    }
  }]
};

const average = M.customPick(day, day.groups[0], M.parseMix("avg"), methods, "morning", false, null);
// A is (0.2+0.4)/2 = 0.3 and B is (0.5+0.1)/2 = 0.3, so both stay.
assertEqual(average.pids.slice().sort(), [1, 2], "tie keeps both");
assertEqual(average.hit, 0.5, "tie hit");

const majority = M.customPick(day, day.groups[0], M.parseMix("maj"), methods, "morning", false, null);
assertEqual(majority.pids, [1], "A is on two methods");
assertEqual(majority.hit, 1, "majority hit from the stored pick");

const list2 = M.customPick(day, day.groups[0], M.parseMix("2=rate"), methods, "morning", false, null);
assertEqual(list2.name, "B", "list 1 stays the model when only list 2 is set");
const list1 = M.customPick(day, day.groups[0], M.parseMix("1=rate"), methods, "morning", false, null);
assertEqual(list1.pids, [1], "list 1 follows the rate method");
assertEqual(list1.hit, 1, "stored hit");

const full = M.customPick(day, day.groups[0], M.defaultMix(), methods, "full_day", false, null);
assertEqual(full.pids, [1], "full day model pick");
assertEqual(full.hit, 1, "full day hit");
assertEqual(M.hasFullDay(day), true, "toggle when full_day is present");
assertEqual(M.hasFullDay({groups: [{}]}), false, "no toggle");

function slate(date, hits, phase) {
  return {
    date: date,
    status: "graded",
    phase: phase || "regular",
    groups: [1, 2, 3].map(function (id) {
      var hit = hits[id - 1];
      return {
        id: id,
        status: hit == null ? "pending" : "graded",
        hit: id === 1 ? hit : 0,
        pick: {pids: [id], name: "P" + id, probability: 0.2, hit: id === 1 ? hit : 0},
        method_picks: {model: {pids: [id], name: "P" + id, probability: 0.2, hit: id === 1 ? hit : 0}},
        players: []
      };
    })
  };
}

const hitDays = [];
for (let i = 1; i <= 14; i++) {
  const iso = "2025-01-" + (i < 10 ? "0" + i : String(i));
  hitDays.push(slate(iso, [1, 0, 0]));
}
assertEqual(M.computeMetrics(hitDays.slice(0, 13), "model", M.defaultMix(), methods, "combined", "morning").streaks, 1, "13 game days is one streak");
assertEqual(M.computeMetrics(hitDays, "model", M.defaultMix(), methods, "combined", "morning").streaks, 2, "14 game days is two streaks");

const withGap = hitDays.slice(0, 3).concat([
  {date: "2025-01-04", status: "pending", phase: "regular", groups: [{id: 1, status: "pending", players: []}]}
]).concat(hitDays.slice(3, 6));
assertEqual(M.computeMetrics(withGap, "model", M.defaultMix(), methods, "combined", "morning").streaks, 0, "a day with no games does not finish or break a run of 6");
assertEqual(M.computeMetrics(withGap, "model", M.defaultMix(), methods, "combined", "morning").days, 6, "gap day is not a game day");

const miss = hitDays.slice(0, 3).concat([slate("2025-01-04", [0, 0, 0])]).concat(hitDays.slice(4, 7));
assertEqual(M.computeMetrics(miss, "model", M.defaultMix(), methods, "combined", "morning").streaks, 0, "a miss resets the run");

const mixed = [slate("2025-04-01", [1, 0, 0], "playoffs"), slate("2025-01-02", [0, 0, 0], "regular")];
const playoff = M.computeMetrics(mixed, "model", M.defaultMix(), methods, "playoffs", "morning");
assertEqual(playoff.picks, 3, "playoff filter");
assertEqual(playoff.days_with_hit, 1, "one playoff day with a scorer");
const combined = M.computeMetrics(mixed, "model", M.defaultMix(), methods, "combined", "morning");
assertEqual(combined.picks, 6, "combined counts both phases");
assertEqual(combined.hit_rate, 1 / 6, "one scored pick of six");

const stored = M.storedMetrics({
  metrics: {model: {regular: {hit_rate: 0.5, hits: 1, picks: 2, days_with_hit: 1, days: 1, streaks: 0}}}
}, "model", "regular");
assertEqual(stored.hit_rate, 0.5, "precomputed metrics");
assertEqual(M.storedMetrics({metrics: {model: {regular: stored}}}, "custom", "regular"), null, "custom is not read from the file");
assertEqual(M.storedMetrics({metrics: {playoffs: {model: {hit_rate: 0.25, picks: 4, hits: 1, days_with_hit: 1, streaks: 0}}}}, "model", "playoffs").picks, 4, "phase-first metrics");

const published = [
  {id: "model", label: "Logistic model (player form + matchup)", kind: "probability"},
  {id: "ddh_style", label: "Scoring-rate estimate", kind: "probability"},
  {id: "goals", label: "Goals per game", kind: "rank"}
];
const fixed = M.aggregateMix(published);
assertEqual(fixed.lists["1"], "ddh_style", "aggregate list 1 is the scoring-rate estimate");
assertEqual(fixed.lists["2"], "model", "aggregate list 2 is the logistic model");
assertEqual(fixed.lists["3"], "model", "aggregate list 3 is the logistic model");
assertEqual(fixed.phases.playoffs, "model", "playoffs use the logistic model on every list");
assertEqual(M.AGGREGATE.label, "Aggregate", "aggregate name");
const aggDay = {
  date: "2025-11-02",
  status: "graded",
  phase: "regular",
  groups: [1, 2].map(function (id) {
    return {
      id: id,
      status: "graded",
      hit: 0,
      players: [],
      method_picks: {
        model: {pids: [10 + id], name: "Model " + id, probability: 0.2, hit: 0},
        ddh_style: {pids: [20 + id], name: "Rate " + id, probability: 0.4, hit: 1}
      }
    };
  })
};
assertEqual(M.customPick(aggDay, aggDay.groups[0], M.aggregateMix(published), published, "morning", false, null).name, "Rate 1", "list 1 uses the scoring-rate pick");
assertEqual(M.customPick(aggDay, aggDay.groups[1], M.aggregateMix(published), published, "morning", false, null).name, "Model 2", "list 2 uses the logistic pick");
const playoffDay = JSON.parse(JSON.stringify(aggDay));
playoffDay.phase = "playoffs";
assertEqual(M.customPick(playoffDay, playoffDay.groups[0], M.aggregateMix(published), published, "morning", false, null).name, "Model 1", "playoff list 1 uses the logistic pick");
assertEqual(M.groupHit(playoffDay, playoffDay.groups[0], "aggregate", M.defaultMix(), published, "morning", false, null), 0, "playoff aggregate hit follows the logistic pick");
assertEqual(M.computeMetrics([playoffDay], "aggregate", M.defaultMix(), published, "playoffs", "morning").hits, 0, "playoff aggregate records use the logistic model");
assertEqual(M.computeMetrics([aggDay], "aggregate", M.defaultMix(), published, "combined", "morning").hits, 1, "aggregate records do not follow the custom mix");

function gradedGroup(id, modelTop, rateTop, random) {
  return {
    id: id,
    status: "graded",
    random: random,
    players: [{pid: 1}, {pid: 2}, {pid: 3}, {pid: 4}],
    method_picks: {
      model: {pids: [1], top3_hits: modelTop, probability: 0.2, hit: 0},
      ddh_style: {pids: [2], top3_hits: rateTop, probability: 0.4, hit: 1}
    }
  };
}
const rateDays = [{
  date: "2026-11-02",
  phase: "regular",
  groups: [gradedGroup(1, 1, 3, 0.5), gradedGroup(2, 2, 0, 0.5), gradedGroup(3, 0, 1, 0.5)]
}];
const aggRates = M.mixRates(rateDays, M.aggregateMix(published), published);
assertEqual(aggRates.top3_rate, 5 / 9, "list 1 uses the scoring-rate top 3");
assertEqual(aggRates.random_baseline, 0.5, "random baseline ignores the method");
const modelRates = M.mixRates(rateDays, M.defaultMix(), published);
assertEqual(modelRates.top3_rate, 3 / 9, "all-model top 3 is the logistic top 3");
const playoffRates = M.mixRates([{
  date: "2026-04-20",
  phase: "playoffs",
  groups: rateDays[0].groups
}], M.aggregateMix(published), published);
assertEqual(playoffRates.top3_rate, 3 / 9, "playoff aggregate top 3 follows the logistic model");

console.log("mix ok");
