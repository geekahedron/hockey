/* Custom mix stays in the method menu. A setting hides it from the other lists. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.join(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");
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

const context = {window: {}};
vm.runInNewContext(mix, context);
vm.runInNewContext(
  [
    grab("mixApi"),
    grab("customRowsVisible"),
    grab("mixPanelOpen"),
    grab("shortMethod"),
    grab("mixSummary"),
    "this.customRowsVisible = customRowsVisible;",
    "this.mixPanelOpen = mixPanelOpen;",
    "this.mixSummary = mixSummary;"
  ].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

assertEqual(context.customRowsVisible(false, "aggregate"), false, "off hides the extra rows");
assertEqual(context.customRowsVisible(false, "model"), false, "off hides rows for the logistic model");
assertEqual(context.customRowsVisible(false, "custom"), true, "selecting Custom mix still shows its rows");
assertEqual(context.customRowsVisible(true, "aggregate"), true, "on shows the rows beside other methods");

assertEqual(context.mixPanelOpen(null, null), true, "first visit starts open");
assertEqual(context.mixPanelOpen(null, ""), true, "an untouched default mix stays open");
assertEqual(context.mixPanelOpen(null, "1=rate"), false, "collapsed after the first setup");
assertEqual(context.mixPanelOpen("closed", ""), false, "a saved collapse stays closed");
assertEqual(context.mixPanelOpen("open", "avg"), true, "a saved expand stays open");

const methods = [
  {id: "model", label: "Logistic model (player form + matchup)"},
  {id: "rate", label: "Scoring-rate estimate"},
  {id: "goals", label: "Goals per game"}
];
const base = {preset: "", lists: {"1": "model", "2": "model", "3": "model"}, months: {}, phases: {}};
assertEqual(context.mixSummary(base, methods), "Per list \u00b7 Logistic", "default summary");
assertEqual(
  context.mixSummary({preset: "average", lists: base.lists, months: {}, phases: {}}, methods),
  "Average of probabilities",
  "average summary"
);
assertEqual(
  context.mixSummary({
    preset: "",
    lists: {"1": "model", "2": "rate", "3": "goals"},
    months: {"11": "rate"},
    phases: {playoffs: "model"}
  }, methods),
  "1 Logistic \u00b7 2 Scoring rate \u00b7 3 Goals/game \u00b7 Nov Scoring rate \u00b7 Playoffs Logistic",
  "per-list summary"
);

if (html.indexOf("Show custom mix") < 0) throw new Error("settings toggle missing");
if (html.indexOf('id="show-custom"') < 0) throw new Error("toggle id missing");
if (/id="show-custom"[^>]*checked/.test(html)) throw new Error("toggle defaults on");

const menu = grab("fillMethodSelect");
if (menu.indexOf("trackMethods") < 0) throw new Error("method menu lost Custom mix");
if (menu.indexOf("listedMethods") >= 0) throw new Error("method menu follows the hide toggle");

["renderSummary", "renderMetrics", "renderSeason"].forEach(function (name) {
  if (grab(name).indexOf("listedMethods") < 0) throw new Error(name + " still lists a hidden custom mix");
});
const season = grab("renderSeason");
if (season.indexOf("withoutHiddenCustom") < 0) throw new Error("charts ignore the toggle");
const panel = grab("renderMixPanel");
if (panel.indexOf('aria-expanded') < 0 || panel.indexOf('aria-controls') < 0) throw new Error("mix header is not a disclosure");
if (panel.indexOf("mix-summary") < 0) throw new Error("collapsed header has no summary");
if (app.indexOf('writeStored("hockey.showCustom"') < 0) throw new Error("toggle is not stored");
if (app.indexOf('writeStored("hockey.mixPanel"') < 0) throw new Error("collapse is not stored");

console.log("custom toggle ok");
