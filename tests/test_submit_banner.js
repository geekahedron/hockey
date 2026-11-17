/* When to submit the three Tims picks together. Today only. */
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
  "pct", "pOf", "torontoClock", "startIso", "submitRule", "availableAt",
  "torontoMinutes", "playoffSlate", "listSize", "modelTop", "chosenTop", "pickStartsSoon",
  "slateChance", "submitAdvice"
];
const context = {};
vm.runInNewContext(
  names.map(grab).concat(["this.submitRule = submitRule; this.submitAdvice = submitAdvice;"]).join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

const rule = context.submitRule();
assertEqual(rule.minChance, 0.73, "threshold");
assertEqual(rule.cutoffHour, 17, "cutoff hour");
assertEqual(rule.cutoffMinute, 0, "cutoff minute");
assertEqual(rule.timeZone, "America/Toronto", "zone");
assertEqual(
  rule.footnote,
  "Backtest: +0.07 hits/day (~+2.5 pts hit rate) vs always-morning, positive in all 5 seasons.",
  "footnote"
);

function player(pid, name, prob, extra) {
  const row = {pid: pid, name: name, team: "EDM", opp: "SJS", home: 1, probability: {model: prob}, available: true};
  Object.keys(extra || {}).forEach(function (key) { row[key] = extra[key]; });
  return row;
}

function day(probs, extra) {
  const doc = {
    date: "2026-11-16",
    phase: "regular",
    groups: probs.map(function (prob, index) {
      return {
        id: index + 1,
        players: [
          player(index * 10 + 1, "Low", 0.05),
          player(index * 10 + 2, "Pick", prob)
        ]
      };
    })
  };
  Object.keys(extra || {}).forEach(function (key) { doc[key] = extra[key]; });
  return doc;
}

// 10:00 ET, before the cutoff. 0.5 three times is S = 0.875.
const morning = Date.parse("2026-11-16T15:00:00Z");
const strong = context.submitAdvice(day([0.5, 0.5, 0.5]), morning);
assertEqual(strong.tone, "strong", "strong tone");
assertEqual(strong.chance >= rule.minChance, true, "above the threshold");
assertEqual(
  strong.text,
  "Strong slate: submit these three now (87.5% chance of at least one hit)",
  "strong copy"
);
assertEqual(strong.footnote, rule.footnote, "strong footnote");

const low = context.submitAdvice(day([0.2, 0.2, 0.2]), morning);
assertEqual(low.tone, "low", "low tone");
assertEqual(
  low.text,
  "Low-confidence slate (48.8% chance of at least one hit). Later lists have scored slightly better on average; check back after 5 PM to submit all three.",
  "low copy"
);

// 5:00 PM ET is the cutoff, even when the slate is strong.
const five = Date.parse("2026-11-16T22:00:00Z");
assertEqual(context.submitAdvice(day([0.5, 0.5, 0.5]), five).text, "Submit these three now", "at 5 PM");
const before = Date.parse("2026-11-16T21:59:00Z");
assertEqual(context.submitAdvice(day([0.2, 0.2, 0.2]), before).tone, "low", "one minute before 5");

// A current pick starting within 30 minutes submits now.
const soon = day([0.2, 0.2, 0.2]);
soon.groups[0].players[1].start = "2026-11-16T15:20:00Z";
assertEqual(context.submitAdvice(soon, morning).text, "Submit these three now", "game within 30 min");

// An unavailable player with a higher probability is not the current pick.
const scratched = day([0.2, 0.2, 0.2]);
scratched.groups[0].players.push(player(99, "Out", 0.95, {available: false}));
assertEqual(context.submitAdvice(scratched, morning).tone, "low", "ignore scratched leader");

// One player left on a list.
const thin = day([0.5, 0.5, 0.5]);
thin.groups[2].players = [player(30, "Last", 0.1)];
assertEqual(context.submitAdvice(thin, morning).text, "Submit these three now", "list about to empty");

// Playoffs never wait.
const playoffs = context.submitAdvice(day([0.2, 0.2, 0.2], {phase: "playoffs"}), morning);
assertEqual(playoffs.text, "Submit these three now", "playoffs");

const mixSrc = fs.readFileSync(path.join(__dirname, "..", "web", "mix.js"), "utf8");
const mixBox = {window: {}};
vm.runInNewContext(mixSrc, mixBox);
const rateId = "ddh_style";
context.state = {
  method: "custom",
  evalMode: "morning",
  mix: {preset: "", lists: {"1": rateId, "2": "model", "3": "model"}, months: {}, phases: {}}
};
context.mixApi = function () { return mixBox.window.HockeyMix; };
context.knownMethods = function () {
  return [
    {id: "model", label: "Logistic model (player form + matchup)", kind: "probability"},
    {id: rateId, label: "Scoring-rate estimate", kind: "probability"},
    {id: "hch_style", label: "Goals per game", kind: "rank"}
  ];
};
function mixDay() {
  function group(id, modelP, rateP, modelPid, ratePid) {
    return {
      id: id,
      status: "pending",
      hit: null,
      players: [
        {pid: modelPid, name: "Model", available: true, probability: {model: modelP, ddh_style: 0.1}},
        {pid: ratePid, name: "Rate", available: true, probability: {model: 0.1, ddh_style: rateP}}
      ],
      method_picks: {
        model: {pids: [modelPid], name: "Model", probability: modelP},
        ddh_style: {pids: [ratePid], name: "Rate", probability: rateP}
      }
    };
  }
  return {
    date: "2026-11-16",
    status: "pending",
    phase: "regular",
    groups: [group(1, 0.4, 0.6, 1, 2), group(2, 0.2, 0.9, 3, 4), group(3, 0.2, 0.9, 5, 6)]
  };
}
const mixed = context.submitAdvice(mixDay(), morning);
assertEqual(mixed.tone, "strong", "custom mix uses list 1 rate and lists 2 and 3 model");
assertEqual(Math.round(mixed.chance * 1000) / 1000, 0.744, "1 - 0.4 * 0.8 * 0.8");
context.state.method = "aggregate";
const aggregate = context.submitAdvice(mixDay(), morning);
assertEqual(aggregate.tone, "strong", "aggregate banner uses the fixed mix");
assertEqual(Math.round(aggregate.chance * 1000) / 1000, 0.744, "aggregate chance matches the fixed lists");

const todayFn = grab("renderToday");
const pastFn = grab("renderPast");
if (todayFn.indexOf("renderSubmitBanner") < 0) throw new Error("banner missing on today");
if (pastFn.indexOf("renderSubmitBanner") >= 0) throw new Error("banner shown on past days");

console.log("submit banner ok");
