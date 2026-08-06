const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

class FakeElement {
  constructor({ dataset = {}, value = "" } = {}) {
    this.children = [];
    this.dataset = dataset;
    this.listeners = new Map();
    this.value = value;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  append(...elements) {
    elements.forEach((element) => {
      const currentIndex = this.children.indexOf(element);
      if (currentIndex !== -1) this.children.splice(currentIndex, 1);
      this.children.push(element);
    });
  }

  dispatch(type) {
    (this.listeners.get(type) || []).forEach((listener) => listener({ type }));
  }
}

const makeRow = (team, lastSubmissionDate) =>
  new FakeElement({ dataset: { team, lastSubmissionDate } });

const makeBoard = (name, rows) => {
  const body = new FakeElement();
  body.children = [...rows];
  body.querySelectorAll = (selector) =>
    selector === "tr[data-last-submission-date]" ? body.children : [];

  const board = new FakeElement({ dataset: { teamBoard: name } });
  board.querySelector = (selector) => (selector === "tbody" ? body : null);
  return { board, body };
};

test("team overview sorts each board by its mode-specific last update time", (t) => {
  const overall = makeBoard("overall", [
    makeRow("Alpha", "2026-07-01T00:00:00Z"),
    makeRow("Beta", "2026-07-10T00:00:00Z"),
    makeRow("Gamma", ""),
    makeRow("Delta", "invalid"),
  ]);
  const late = makeBoard("late", [
    makeRow("Alpha", "2026-07-12T00:00:00Z"),
    makeRow("Beta", "2026-07-02T00:00:00Z"),
    makeRow("Gamma", ""),
  ]);
  const teamSortOrder = new FakeElement({ value: "updated-desc" });

  global.document = {
    querySelector: (selector) => (selector === "#team-sort-order" ? teamSortOrder : null),
    querySelectorAll: (selector) => {
      if (selector === "[data-team-board]") return [overall.board, late.board];
      return [];
    },
  };
  t.after(() => delete global.document);

  const appPath = path.resolve(__dirname, "../assets/js/app.js");
  delete require.cache[require.resolve(appPath)];
  require(appPath);

  const teams = (body) => body.children.map((row) => row.dataset.team);
  assert.deepEqual(teams(overall.body), ["Beta", "Alpha", "Gamma", "Delta"]);
  assert.deepEqual(teams(late.body), ["Alpha", "Beta", "Gamma"]);

  teamSortOrder.value = "updated-asc";
  teamSortOrder.dispatch("change");
  assert.deepEqual(teams(overall.body), ["Alpha", "Beta", "Gamma", "Delta"]);
  assert.deepEqual(teams(late.body), ["Beta", "Alpha", "Gamma"]);

  teamSortOrder.value = "ranking";
  teamSortOrder.dispatch("change");
  assert.deepEqual(teams(overall.body), ["Alpha", "Beta", "Gamma", "Delta"]);
  assert.deepEqual(teams(late.body), ["Alpha", "Beta", "Gamma"]);
});
