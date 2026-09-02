const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

class FakeElement {
  constructor(dataset = {}, value = "") {
    this.dataset = dataset;
    this.value = value;
    this.children = [];
    this.listeners = new Map();
    this.hidden = false;
    this.textContent = "";
  }

  addEventListener(type, listener) {
    this.listeners.set(type, [...(this.listeners.get(type) || []), listener]);
  }

  dispatch(type) {
    (this.listeners.get(type) || []).forEach((listener) => listener({ type }));
  }

  append(...nodes) {
    this.children.push(...nodes);
  }
}

const makeTimeElement = (className, dateTime) => ({
  dateTime,
  textContent: dateTime,
  classList: { contains: (name) => name === className },
});

const makeCard = (dataset, teams) => {
  const card = new FakeElement(dataset);
  const rows = teams.map((team) => new FakeElement({ team }));
  card.querySelector = (selector) =>
    rows.find((row) => selector === `[data-team="${row.dataset.team}"]`) || null;
  card.querySelectorAll = (selector) => (selector === "tbody tr[data-team]" ? rows : []);
  card.rows = rows;
  return card;
};

const loadApp = (t, elements, cards, times = []) => {
  const controls = new Map(Object.entries(elements));
  global.CSS = { escape: (value) => value };
  global.document = {
    querySelector: (selector) => controls.get(selector) || null,
    querySelectorAll: (selector) => {
      if (selector === ".competition") return cards;
      if (selector === ".local-date, .local-time") return times;
      return [];
    },
    createElement: () => new FakeElement(),
  };
  t.after(() => {
    delete global.document;
    delete global.CSS;
  });

  const appPath = path.resolve(__dirname, "../assets/js/app.js");
  delete require.cache[require.resolve(appPath)];
  require(appPath);
};

const filterFixture = (t) => {
  const elements = {
    "#search": new FakeElement(),
    "#team-filter": new FakeElement(),
    "#category-filter": new FakeElement(),
    "#state-filter": new FakeElement(),
    "#result-count": new FakeElement(),
    "#filter-empty": new FakeElement(),
  };
  const cards = [
    makeCard(
      { title: "vision cup", category: "Featured", state: "active", teams: "alpha|beta|" },
      ["Alpha", "Beta"],
    ),
    makeCard(
      { title: "signal cup", category: "Playground", state: "ended", teams: "beta|" },
      ["Beta"],
    ),
  ];
  loadApp(t, elements, cards);
  return { elements, cards };
};

test("timestamps are rendered in the reader's locale", (t) => {
  const times = [
    makeTimeElement("local-date", "2026-07-16T08:42:00Z"),
    makeTimeElement("local-time", "2026-07-16T08:42:00Z"),
    makeTimeElement("local-date", "not-a-date"),
  ];
  loadApp(t, {}, [], times);

  assert.match(times[0].textContent, /2026/u);
  assert.match(times[1].textContent, /2026/u);
  assert.ok(times[1].textContent.length > times[0].textContent.length);
  assert.equal(times[2].textContent, "not-a-date");
});

test("the category filter is built from the rendered competitions", (t) => {
  const { elements } = filterFixture(t);
  assert.deepEqual(
    elements["#category-filter"].children.map((option) => option.value),
    ["Featured", "Playground"],
  );
});

test("search, team, category and state filters narrow the competition list", (t) => {
  const { elements, cards } = filterFixture(t);
  const visible = () => cards.filter((card) => !card.hidden).map((card) => card.dataset.title);

  elements["#search"].value = "vision";
  elements["#search"].dispatch("input");
  assert.deepEqual(visible(), ["vision cup"]);
  assert.equal(elements["#result-count"].textContent, "显示 1 / 2 场");
  assert.equal(elements["#filter-empty"].hidden, true);

  elements["#search"].value = "";
  elements["#state-filter"].value = "ended";
  elements["#state-filter"].dispatch("change");
  assert.deepEqual(visible(), ["signal cup"]);

  elements["#state-filter"].value = "";
  elements["#category-filter"].value = "Featured";
  elements["#category-filter"].dispatch("change");
  assert.deepEqual(visible(), ["vision cup"]);

  elements["#category-filter"].value = "";
  elements["#search"].value = "nothing matches";
  elements["#search"].dispatch("input");
  assert.deepEqual(visible(), []);
  assert.equal(elements["#filter-empty"].hidden, false);
});

test("a team filter also hides the other teams' rows inside a competition", (t) => {
  const { elements, cards } = filterFixture(t);

  elements["#team-filter"].value = "Beta";
  elements["#team-filter"].dispatch("change");
  assert.deepEqual(
    cards.map((card) => card.rows.filter((row) => !row.hidden).map((row) => row.dataset.team)),
    [["Beta"], ["Beta"]],
  );

  elements["#team-filter"].value = "Alpha";
  elements["#team-filter"].dispatch("change");
  assert.deepEqual(
    cards.map((card) => card.hidden),
    [false, true],
  );
});
