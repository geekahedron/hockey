/* Past days keep real Tims scratches and drop the game-started treatment. */
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

const context = {state: {backtest: false}};
vm.runInNewContext(
  [
    grab("isAvailable"),
    grab("gameStartedFirst"),
    grab("torontoClock"),
    grab("torontoDate"),
    grab("slateIsPast"),
    grab("timsRemoved"),
    grab("offListForDisplay"),
    grab("removedNote"),
    "this.torontoDate = torontoDate;",
    "this.slateIsPast = slateIsPast;",
    "this.offListForDisplay = offListForDisplay;",
    "this.removedNote = removedNote;",
    "this.state = state;"
  ].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

const today = context.torontoDate();
const started = {
  name: "Early",
  available: false,
  game_started: true,
  unavailable_reason: "game_started",
  start: "2026-11-16T19:00:00-05:00",
  game_started_at: "2026-11-16T19:00:00-05:00"
};
const scratch = {
  name: "Depth",
  available: false,
  unavailable_reason: "removed",
  removed_at: "2026-11-16T18:00:00-05:00",
  start: "2026-11-16T19:00:00-05:00"
};
const past = {date: "2026-11-16"};
const live = {date: today};

assertEqual(context.slateIsPast(past), true, "yesterday is past");
assertEqual(context.slateIsPast(live), false, "toronto today is live");
assertEqual(context.offListForDisplay(started, past), false, "past day does not gray a started game");
assertEqual(context.removedNote(started, past), "", "past day has no game-started note");
assertEqual(context.offListForDisplay(scratch, past), true, "past day still grays a scratch");
assertEqual(
  context.removedNote(scratch, past),
  "Removed from the Tims list at 18:00",
  "scratch keeps its removal time"
);
assertEqual(context.offListForDisplay(started, live), true, "today still grays a started game");
assertEqual(context.removedNote(started, live).indexOf("Game started") === 0, true, "today keeps the game-started note");
assertEqual(
  context.removedNote(scratch, live),
  "Removed from the Tims list at 18:00",
  "today still names a scratch"
);

context.state.backtest = true;
assertEqual(context.slateIsPast(live), true, "backtest season is past");
assertEqual(context.offListForDisplay(started, live), false, "backtest hides a started game");
assertEqual(context.removedNote(scratch, live), "Removed from the Tims list at 18:00", "backtest keeps a scratch");
context.state.backtest = false;

console.log("past started ok");
