/* First visit opens on a custom mix. A saved choice stays put. */
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
  [grab("scoringRateId"), grab("initialView"),
    "this.scoringRateId = scoringRateId; this.initialView = initialView;"
  ].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

const methods = [
  {id: "model", label: "Logistic model (player form + matchup)", kind: "probability"},
  {id: "ddh_style", label: "Scoring-rate estimate", kind: "probability"},
  {id: "hch_style", label: "Goals per game", kind: "rank"}
];
assertEqual(context.scoringRateId(methods), "ddh_style", "scoring-rate id");
assertEqual(methods[1].label, "Scoring-rate estimate", "public name");

const fresh = context.initialView(null, null, null, null);
assertEqual(fresh.fresh, true, "no storage is a first visit");
assertEqual(fresh.method, "custom", "first visit uses the custom mix");

const savedModel = context.initialView("", "model", null, null);
assertEqual(savedModel.fresh, false, "empty saved mix is a choice");
assertEqual(savedModel.method, "model", "saved logistic model stays");

const savedCustom = context.initialView("1=ddh_style", "custom", null, null);
assertEqual(savedCustom.method, "custom", "saved custom mix stays");

const query = context.initialView(null, null, "2=hch_style", "model");
assertEqual(query.fresh, false, "a mix in the url is not a first visit");
assertEqual(query.method, "model", "url method wins");

console.log("visitor mix ok");
