(() => {
  "use strict";

  const formatDate = (value, withTime = false) => {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return value;
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "short",
      day: "numeric",
      ...(withTime
        ? { hour: "2-digit", minute: "2-digit", timeZoneName: "short" }
        : {}),
    }).format(date);
  };

  document.querySelectorAll(".local-date, .local-time").forEach((element) => {
    element.textContent = formatDate(element.dateTime, element.classList.contains("local-time"));
  });

  const cards = [...document.querySelectorAll(".competition")];
  const search = document.querySelector("#search");
  const teamFilter = document.querySelector("#team-filter");
  const categoryFilter = document.querySelector("#category-filter");
  const stateFilter = document.querySelector("#state-filter");
  const resultCount = document.querySelector("#result-count");
  const emptyState = document.querySelector("#filter-empty");
  if (!cards.length || !search || !teamFilter || !categoryFilter || !stateFilter) return;

  [...new Set(cards.map((card) => card.dataset.category).filter(Boolean))]
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

    cards.forEach((card) => {
      const visible = Boolean(
        (!query || `${card.dataset.title} ${card.dataset.teams}`.includes(query)) &&
          (!team || card.querySelector(`[data-team="${CSS.escape(team)}"]`)) &&
          (!category || card.dataset.category === category) &&
          (!state || card.dataset.state === state),
      );
      card.hidden = !visible;
      if (visible) visibleCount += 1;

      card.querySelectorAll("tbody tr[data-team]").forEach((row) => {
        row.hidden = Boolean(team && row.dataset.team !== team);
      });
    });

    if (resultCount) resultCount.textContent = `显示 ${visibleCount} / ${cards.length} 场`;
    if (emptyState) emptyState.hidden = visibleCount !== 0;
  };

  [search, teamFilter, categoryFilter, stateFilter].forEach((control) => {
    control.addEventListener(control === search ? "input" : "change", applyFilters);
  });
})();
