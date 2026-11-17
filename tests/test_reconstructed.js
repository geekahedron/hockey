/* Reconstructed days keep a label and a chart mark, and stay in the totals. */
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
  [grab("reconstructedLabel"), "this.reconstructedLabel = reconstructedLabel;"].join("\n"),
  context
);

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": " + JSON.stringify(actual) + " !== " + JSON.stringify(expected));
}

assertEqual(context.reconstructedLabel({}), "", "ordinary day");
assertEqual(
  context.reconstructedLabel({reconstructed: true}),
  "Reconstructed from historical data \u2014 live tracking began Nov 2",
  "reconstructed label"
);
if (src.indexOf("spec.reconstructed") < 0) throw new Error("charts do not mark reconstructed dates");

console.log("reconstructed ok");
