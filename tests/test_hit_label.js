/* A graded day with no hit is not still pending. */
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
  [grab("hitText"), "this.hitText = hitText;"].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

assertEqual(context.hitText(null, "graded"), "not graded", "graded day with a null hit");
assertEqual(context.hitText(null, "pending"), "Pending", "game still going");
assertEqual(context.hitText(null), "Pending", "no status yet");
assertEqual(context.hitText(1, "graded"), "Hit", "scored");
assertEqual(context.hitText(0, "graded"), "Miss", "miss");
assertEqual(context.hitText(0.5, "graded"), "50% of tie", "split");

console.log("hit label ok");
