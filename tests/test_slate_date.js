/* The Today page names the slate date and does not treat a stale file as today. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const app = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");

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

const context = {};
vm.runInNewContext(
  [grab("torontoDate"), grab("prominentDate"), grab("slateCurrent"), grab("staleNote"),
    "this.prominentDate = prominentDate; this.slateCurrent = slateCurrent; this.staleNote = staleNote;"
  ].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

assertEqual(context.prominentDate("2026-11-20"), "Friday, Nov 20, 2026", "long date");
assertEqual(context.prominentDate("2026-11-19"), "Thursday, Nov 19, 2026", "previous day");
assertEqual(context.prominentDate(""), "", "blank");

const morning = Date.parse("2026-11-20T11:23:00Z");
assertEqual(context.slateCurrent({date: "2026-11-20"}, morning), true, "6:23 AM Toronto matches the file");
assertEqual(context.slateCurrent({date: "2026-11-19"}, morning), false, "yesterday is stale at 6:23 AM");
assertEqual(context.slateCurrent(null, morning), false, "missing file is not current");

const today = grab("renderToday");
const hold = today.indexOf("todayLoading || state.todayStale");
const picks = today.indexOf("renderTodayPicks");
if (hold < 0 || picks < 0 || hold > picks) throw new Error("a stale slate still renders today's picks");
if (today.indexOf("renderSlateStatus") < 0) throw new Error("date is not at the top of today");

const refresh = grab("refreshToday");
if (refresh.indexOf('fetch("refresh.php"') < 0 || refresh.indexOf('method: "POST"') < 0) {
  throw new Error("stale page does not ask the server to publish");
}
if (refresh.indexOf("application/x-www-form-urlencoded") < 0 || refresh.indexOf('body: "refresh=1"') < 0) {
  throw new Error("refresh POST has no form body");
}
if (refresh.indexOf('load("today.json")') < 0) throw new Error("refresh does not re-read today.json");
assertEqual(context.staleNote(true, true, "no_games"), "Loading today's data\u2026", "loading wins");
assertEqual(context.staleNote(false, false, "no_games"), "", "current slate has no note");
assertEqual(
  context.staleNote(false, true, "no_games"),
  "No NHL games today, so there are no Tims lists.",
  "off day"
);
assertEqual(
  context.staleNote(false, true, ""),
  "Today's lists aren't available yet",
  "lists not posted"
);
if (app.indexOf("No NHL games today, so there are no Tims lists.") < 0) throw new Error("missing no-games note");
if (refresh.indexOf('body.status === "no_games"') < 0) throw new Error("page ignores no_games");

console.log("slate date ok");
