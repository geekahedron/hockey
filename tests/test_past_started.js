/* Past days keep real Tims scratches and drop the game-started treatment.
   Partial availability is a Toronto time range, not a removal stamp. */
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
    grab("torontoGameTime"),
    grab("torontoDate"),
    grab("slateIsPast"),
    grab("timsRemoved"),
    grab("offListForDisplay"),
    grab("openingIso"),
    grab("onFirstList"),
    grab("availabilityNote"),
    grab("removedNote"),
    "this.torontoDate = torontoDate;",
    "this.slateIsPast = slateIsPast;",
    "this.offListForDisplay = offListForDisplay;",
    "this.availabilityNote = availabilityNote;",
    "this.removedNote = removedNote;",
    "this.state = state;"
  ].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

const today = context.torontoDate();
const open = "2026-11-16T00:00:00-05:00";
const past = {date: "2026-11-16", generated_at: open, morning: {at: open, groups: []}};
const live = {date: today, generated_at: open, morning: {at: open, groups: []}};

const started = {
  name: "Early",
  pid: 1,
  available: false,
  game_started: true,
  unavailable_reason: "game_started",
  first_seen: open,
  start: "2026-11-16T19:00:00-05:00",
  game_started_at: "2026-11-16T19:00:00-05:00"
};
const scratch = {
  name: "Depth",
  pid: 2,
  available: false,
  unavailable_reason: "removed",
  first_seen: open,
  removed_at: "2026-11-16T15:00:00-05:00",
  start: "2026-11-16T19:00:00-05:00"
};
const late = {
  name: "Late",
  pid: 3,
  available: true,
  first_seen: "2026-11-16T11:30:00-05:00",
  start: "2026-11-16T19:00:00-05:00"
};

assertEqual(context.slateIsPast(past), true, "yesterday is past");
assertEqual(context.slateIsPast(live), false, "toronto today is live");
assertEqual(context.offListForDisplay(started, past), false, "past day does not gray a started game");
assertEqual(context.availabilityNote(started, past), "", "full window has no range");
assertEqual(context.removedNote(started, past), "", "past day has no game-started note");
assertEqual(context.offListForDisplay(scratch, past), true, "past day still grays a scratch");
assertEqual(context.availabilityNote(scratch, past), "Available until 3:00 PM", "scratch names only the removal");
assertEqual(context.availabilityNote(late, past), "Available 11:30 AM", "late add names only the arrival");
const both = {
  name: "Brief",
  pid: 4,
  available: false,
  unavailable_reason: "removed",
  first_seen: "2026-11-16T11:30:00-05:00",
  removed_at: "2026-11-16T16:15:00-05:00",
  start: "2026-11-16T19:00:00-05:00"
};
assertEqual(context.availabilityNote(both, past), "Available 11:30 AM \u2013 4:15 PM", "late and early names both ends");
assertEqual(context.offListForDisplay(both, past), true, "late scratch stays gray");
assertEqual(context.offListForDisplay(late, past), false, "late add who stayed is not gray");

assertEqual(context.offListForDisplay(started, live), true, "today still grays a started game");
assertEqual(context.removedNote(started, live).indexOf("Game started") === 0, true, "today keeps the game-started note");
assertEqual(context.offListForDisplay(scratch, live), true, "today grays a scratch");
assertEqual(context.availabilityNote(scratch, live), "Available until 3:00 PM", "today scratch uses the same label");
const stillLate = Object.assign({}, late, {start: "2099-11-16T19:00:00-05:00"});
assertEqual(context.availabilityNote(stillLate, live), "Available 11:30 AM", "today late add still listed");
assertEqual(context.offListForDisplay(stillLate, live), false, "open late add is not gray");

context.state.backtest = true;
assertEqual(context.slateIsPast(live), true, "backtest season is past");
assertEqual(context.offListForDisplay(started, live), false, "backtest hides a started game");
assertEqual(context.availabilityNote(scratch, live), "Available until 3:00 PM", "backtest keeps the scratch label");
assertEqual(context.availabilityNote(late, live), "Available 11:30 AM", "backtest names a late add the same way");
context.state.backtest = false;

console.log("past started ok");
