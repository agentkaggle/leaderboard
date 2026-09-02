(() => {
  "use strict";

  const dateStyle = { year: "numeric", month: "short", day: "numeric" };
  const dateFormat = new Intl.DateTimeFormat("zh-CN", dateStyle);
  const timeFormat = new Intl.DateTimeFormat("zh-CN", {
    ...dateStyle,
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });

  const localize = (selector, formatter) => {
    document.querySelectorAll(selector).forEach((element) => {
      const date = new Date(element.dateTime);
      element.textContent = Number.isNaN(date.valueOf())
        ? element.dateTime
        : formatter.format(date);
    });
  };
  localize(".local-date", dateFormat);
  localize(".local-time", timeFormat);

  const search = document.querySelector("#search");
  const teamFilter = document.querySelector("#team-filter");
  const categoryFilter = document.querySelector("#category-filter");
  const stateFilter = document.querySelector("#state-filter");
  const resultCount = document.querySelector("#result-count");
  const emptyState = document.querySelector("#filter-empty");
  const cards = [...document.querySelectorAll(".competition")].map((card) => ({
    card,
    haystack: `${card.dataset.title} ${card.dataset.teams}`,
    rows: [...card.querySelectorAll("tbody tr[data-team]")],
  }));
  if (!cards.length || !search || !teamFilter || !categoryFilter || !stateFilter) return;

  [...new Set(cards.map(({ card }) => card.dataset.category).filter(Boolean))]
    .sort((left, right) => left.localeCompare(right, "zh-CN"))
    .forEach((category) => {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = category;
      categoryFilter.append(option);
    });

  const applyFilters = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const team = teamFilter.value;
    const category = categoryFilter.value;
    const state = stateFilter.value;
    let visibleCount = 0;

    cards.forEach(({ card, haystack, rows }) => {
      const visible = Boolean(
        (!query || haystack.includes(query)) &&
          (!team || rows.some((row) => row.dataset.team === team)) &&
          (!category || card.dataset.category === category) &&
          (!state || card.dataset.state === state),
      );
      card.hidden = !visible;
      if (visible) visibleCount += 1;
      rows.forEach((row) => {
        row.hidden = Boolean(team && row.dataset.team !== team);
      });
    });

    if (resultCount) resultCount.textContent = `显示 ${visibleCount} / ${cards.length} 场`;
    if (emptyState) emptyState.hidden = visibleCount !== 0;
  };

  search.addEventListener("input", applyFilters);
  teamFilter.addEventListener("change", applyFilters);
  categoryFilter.addEventListener("change", applyFilters);
  stateFilter.addEventListener("change", applyFilters);
})();
