const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const visualizationsPath = path.resolve(__dirname, "../assets/js/visualizations.js");
const {
  formatResultTime,
  pointOffsets,
  rankSourceLabel,
  scaleQuantile,
  scoreSourceLabel,
  teamColor,
  teamInitial,
  truncateLabel,
} = require(visualizationsPath);

test("result times are localized safely", () => {
  assert.equal(formatResultTime(""), "Unavailable");
  assert.equal(formatResultTime("not-a-date"), "not-a-date");
  assert.match(formatResultTime("2026-08-05T02:27:44Z"), /2026/u);
});

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
  assert.deepEqual(pointOffsets(3, 76), [-24, 0, 24]);
  assert.equal(truncateLabel("short", 8), "short");
  assert.equal(truncateLabel("比赛成绩分布", 5), "比赛成绩…");
});

test("every account receives a distinct color and a stable short label", () => {
  const colors = Array.from({ length: 24 }, (_, index) => teamColor(index, 24));
  assert.equal(new Set(colors).size, colors.length);
  assert.equal(teamColor(7, 24), teamColor(7, 24));
  assert.equal(teamInitial("FlameZywoo"), "F");
  assert.equal(teamInitial("Changye Li"), "CL");
  assert.equal(teamInitial("Bayes & Beyond"), "BB");
  assert.equal(teamInitial("δ-me13"), "ΔM");
});

test("rank and score labels keep Public, Private, and estimates explicit", () => {
  assert.equal(rankSourceLabel({ rankKind: "official_private" }), "Private rank");
  assert.equal(rankSourceLabel({ rankKind: "authenticated_private" }), "Private rank");
  assert.equal(rankSourceLabel({ rankKind: "official_public" }), "Public rank");
  assert.equal(rankSourceLabel({ rankKind: "late_estimate" }), "Estimated rank*");
  assert.equal(scoreSourceLabel({ scoreKind: "authenticated_private" }), "Private score");
  assert.equal(scoreSourceLabel({ scoreKind: "late_private" }), "Late Private score");
});
