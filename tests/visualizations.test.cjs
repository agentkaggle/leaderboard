const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const visualizationsPath = path.resolve(__dirname, "../assets/js/visualizations.js");
const { pointOffsets, scaleQuantile, truncateLabel } = require(visualizationsPath);

test("quantile scales preserve the endpoints and expand the completed top tail", () => {
  assert.equal(scaleQuantile(0), 0);
  assert.equal(scaleQuantile(80), 0.8);
  assert.equal(scaleQuantile(100), 1);
  assert.equal(scaleQuantile(80, "lens"), 0.24);
  assert.equal(scaleQuantile(95, "lens"), 0.43);
  assert.equal(scaleQuantile(98, "lens"), 0.62);
  assert.equal(scaleQuantile(99, "lens"), 0.78);
  assert.equal(scaleQuantile(100, "lens"), 1);
});

test("point offsets stay centered and labels truncate by Unicode character", () => {
  assert.deepEqual(pointOffsets(1, 76), [0]);
  assert.deepEqual(pointOffsets(3, 76), [-19, 0, 19]);
  assert.equal(truncateLabel("short", 8), "short");
  assert.equal(truncateLabel("比赛成绩分布", 5), "比赛成绩…");
});
