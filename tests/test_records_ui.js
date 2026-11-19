/* Records line and grouped list changes. */
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
  [grab("pct"), grab("countText"), grab("recordLine"), grab("pickTint"), grab("groupChangeLines"), grab("changeLineText"),
    "this.recordLine = recordLine; this.groupChangeLines = groupChangeLines; this.changeLineText = changeLineText; this.pickTint = pickTint;"
  ].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

assertEqual(
  context.recordLine({days: 32, hits: 27, picks: 96, hit_rate: 0.28125, days_with_hit: 8, streaks: 0}),
  "32 days \u00b7 27/96 correct (28.1%) \u00b7 8 with a hit \u00b7 0 streaks",
  "records line"
);
assertEqual(context.recordLine(null), "\u2014", "empty");
assertEqual(context.pickTint(1), "g1", "group 1");
assertEqual(context.pickTint(2), "g2", "group 2");
assertEqual(context.pickTint(3), "g3", "group 3");

const lines = context.groupChangeLines([{
  time: "2026-11-16T20:30:00Z",
  added: [
    {name: "Denver Barkey", group: 3},
    {name: "Eetu Luostarinen", group: 3},
    {name: "Jamie Benn", group: 1}
  ],
  removed: [{name: "Mitch Marner", group: 3}]
}]);
assertEqual(lines.length, 3, "one line per group and change");
assertEqual(context.changeLineText(lines[0], "3:30 PM"), "3:30 PM \u00b7 Added \u00b7 Group 3: Denver Barkey, Eetu Luostarinen", "grouped names");
assertEqual(context.changeLineText(lines[2], "3:30 PM"), "3:30 PM \u00b7 Removed \u00b7 Group 3: Mitch Marner", "removed line");

const css = fs.readFileSync(path.join(__dirname, "..", "web", "style.css"), "utf8");
function has(needle) {
  if (css.indexOf(needle) < 0) throw new Error("missing " + needle);
}
has(".g1{color:#f6c2cc;border-left-color:#e892a6}");
has(".g2{color:#ffc48a;border-left-color:#ff8c1a}");
has(".g3{color:#f6e7a8;border-left-color:#e6cf6a}");
["#b7f3c9", "#3dce73", "#a9d4ff", "#5aa2f0"].forEach(function (old) {
  if (css.indexOf(old) >= 0) throw new Error("old group color still in css: " + old);
});
if (src.indexOf('class: "today-pick " + (pickTint(pick.groupId)') < 0) throw new Error("top box has no group color");
if (src.indexOf("group-chart") < 0) throw new Error("pick charts have no group color");

console.log("records ui ok");
