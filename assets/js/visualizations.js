(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const INK = "#0b0b0b";
  // Validated light-mode categorical slots, each paired with the readable ink for
  // a label drawn inside the mark. Identity is also carried by the initials in the
  // mark, the legend, and the tooltip, so a repeated hue never stands alone.
  const TEAM_COLORS = [
    ["#2a78d6", "#ffffff"],
    ["#eb6834", INK],
    ["#1baf7a", INK],
    ["#eda100", INK],
    ["#e87ba4", INK],
    ["#008300", "#ffffff"],
    ["#4a3aa7", "#ffffff"],
    ["#e34948", INK],
  ];
  const LENS_KNOTS = [
    [0, 0],
    [80, 0.24],
    [95, 0.43],
    [98, 0.62],
    [99, 0.78],
    [100, 1],
  ];

  const scaleQuantile = (quantile, scale = "linear") => {
    const bounded = Math.max(0, Math.min(100, Number(quantile)));
    if (scale !== "lens") return bounded / 100;
    for (let index = 0; index < LENS_KNOTS.length - 1; index += 1) {
      const [leftQ, leftX] = LENS_KNOTS[index];
      const [rightQ, rightX] = LENS_KNOTS[index + 1];
      if (bounded <= rightQ) {
        return leftX + ((bounded - leftQ) / (rightQ - leftQ)) * (rightX - leftX);
      }
    }
    return 1;
  };

  const truncateLabel = (value, maximum = 34) => {
    const characters = Array.from(String(value));
    return characters.length <= maximum
      ? characters.join("")
      : `${characters.slice(0, maximum - 1).join("")}…`;
  };

  const teamColor = (index) => TEAM_COLORS[Math.abs(Number(index) || 0) % TEAM_COLORS.length];

  const teamInitial = (value) => {
    const tokens = String(value)
      .trim()
      .split(/[\s_-]+/u)
      .filter((token) => /[\p{L}\p{N}]/u.test(token));
    if (!tokens.length) return "?";
    const selected = tokens.length > 1 ? tokens.slice(0, 2) : tokens;
    return selected
      .map((token) => Array.from(token)[0] || "")
      .join("")
      .toLocaleUpperCase("en-US");
  };

  const rankSourceLabel = (record) =>
    ({
      official_public: "Public rank",
      official_private: "Private rank",
      authenticated_private: "Private rank",
      late_estimate: "Estimated rank*",
    })[record.rankKind] || "Rank";

  const scoreSourceLabel = (record) =>
    ({
      official_public: "Public score",
      official_private: "Private score",
      authenticated_private: "Private score",
      late_public: "Late Public score",
      late_private: "Late Private score",
    })[record.scoreKind] || "Score";

  const resultTimeFormat = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });

  const formatResultTime = (value) => {
    const rawValue = String(value || "").trim();
    if (!rawValue) return "Unavailable";
    const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/u.test(rawValue)
      ? rawValue
      : `${rawValue.replace(" ", "T")}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.valueOf()) ? rawValue : resultTimeFormat.format(date);
  };

  const svgNode = (name, attributes = {}, text = "") => {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== "") node.textContent = text;
    return node;
  };

  /** Parse each data block once per render; the cache dies with the render. */
  const readRecords = (mount, chartData) => {
    const sourceId = mount.dataset.chartSource;
    if (!chartData.has(sourceId)) {
      const source = document.getElementById(sourceId);
      chartData.set(sourceId, source ? JSON.parse(source.textContent) : []);
    }
    const best = mount.dataset.chartBest === "true";
    return chartData.get(sourceId).flatMap((competition) =>
      (best ? competition.results.slice(0, 1) : competition.results).map((result) => ({
        competition: competition.title,
        team: result.team_name,
        rank: result.rank,
        teamCount: result.leaderboard_team_count,
        topPercent: result.top_percent,
        quantile: result.quantile,
        score: result.score,
        rankKind: result.rank_kind,
        scoreKind: result.score_kind,
        resultTime: result.result_time,
        official: result.is_official,
        provenance: result.provenance,
      })),
    );
  };

  const chartFrame = (mount, width, height) => {
    const wrapper = document.createElement("div");
    wrapper.className = "chart-scroll";
    const title = mount.dataset.chartTitle || "Kaggle quantile chart";
    const svg = svgNode("svg", {
      class: "quantile-chart-svg",
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-label": title,
    });
    svg.append(
      svgNode("title", {}, title),
      svgNode(
        "desc",
        {},
        "Quantile ranges from 0 to 100. A larger value represents a stronger relative leaderboard result.",
      ),
    );
    wrapper.append(svg);
    mount.replaceChildren(wrapper);
    return svg;
  };

  const addAxis = (svg, { left, top, plotWidth, bottom, ticks, scale }) => {
    ticks.forEach((tick) => {
      const x = left + plotWidth * scaleQuantile(tick, scale);
      svg.append(
        svgNode("line", { class: "chart-grid-line", x1: x, y1: top, x2: x, y2: bottom }),
        svgNode(
          "text",
          { class: "chart-axis-label", x, y: top - 14, "text-anchor": "middle" },
          String(tick),
        ),
      );
    });
    svg.append(
      svgNode(
        "text",
        {
          class: "chart-axis-title",
          x: left + plotWidth / 2,
          y: top - 42,
          "text-anchor": "middle",
        },
        scale === "lens" ? "Quantile (%) · high-percentile lens" : "Quantile (%)",
      ),
    );
  };

  /** Diagonal texture so an estimated bar never reads as an official measurement. */
  const latePattern = (svg, id, color) => {
    const pattern = svgNode("pattern", {
      id,
      width: 8,
      height: 8,
      patternUnits: "userSpaceOnUse",
    });
    pattern.append(
      svgNode("rect", { class: "chart-surface-fill", width: 8, height: 8 }),
      svgNode("path", {
        d: "M-2 2 L2 -2 M0 8 L8 0 M6 10 L10 6",
        stroke: color,
        "stroke-width": 2,
      }),
    );
    const definitions = svgNode("defs");
    definitions.append(pattern);
    svg.append(definitions);
  };

  const resultRows = (record) => [
    [
      "Rank",
      `${rankSourceLabel(record)} · #${record.rank.toLocaleString()} / ${record.teamCount.toLocaleString()}`,
    ],
    ["Score", `${scoreSourceLabel(record)} · ${record.score}`],
    ["Result time", formatResultTime(record.resultTime)],
    ["Quantile", `Q${record.quantile.toFixed(2)}`],
    ["Top", `${record.topPercent.toFixed(2)}%`],
  ];

  let tooltipNode;

  const ensureTooltip = () => {
    if (tooltipNode) return tooltipNode;
    tooltipNode = document.createElement("div");
    tooltipNode.id = "chart-result-tooltip";
    tooltipNode.className = "chart-tooltip";
    tooltipNode.setAttribute("role", "tooltip");
    tooltipNode.hidden = true;
    document.body.append(tooltipNode);
    const hide = () => {
      tooltipNode.hidden = true;
    };
    window.addEventListener("scroll", hide, { capture: true, passive: true });
    window.addEventListener("resize", hide);
    return tooltipNode;
  };

  const tooltipTextNode = (name, className, value) => {
    const node = document.createElement(name);
    node.className = className;
    node.textContent = value;
    return node;
  };

  const fillTooltip = (tooltip, record) => {
    const details = document.createElement("dl");
    details.className = "chart-tooltip-details";
    resultRows(record).forEach(([term, value]) => {
      details.append(tooltipTextNode("dt", "", term), tooltipTextNode("dd", "", value));
    });
    tooltip.replaceChildren(
      tooltipTextNode("span", "chart-tooltip-competition", record.competition),
      tooltipTextNode("strong", "chart-tooltip-team", record.team),
      details,
      tooltipTextNode("p", "chart-tooltip-provenance", record.provenance),
    );
  };

  const positionTooltip = (tooltip, clientX, clientY) => {
    const edge = 12;
    const offset = 16;
    tooltip.hidden = false;
    const bounds = tooltip.getBoundingClientRect();
    const left = Math.max(
      edge,
      Math.min(clientX + offset, window.innerWidth - bounds.width - edge),
    );
    const preferredTop = clientY - bounds.height - offset;
    const top = Math.max(
      edge,
      preferredTop >= edge
        ? preferredTop
        : Math.min(clientY + offset, window.innerHeight - bounds.height - edge),
    );
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  };

  const bindRecordTooltip = (node, record) => {
    const tooltip = ensureTooltip();
    node.classList.add("chart-interactive-mark");
    node.setAttribute("tabindex", "0");
    node.setAttribute("aria-describedby", tooltip.id);
    node.setAttribute(
      "aria-label",
      [record.competition, record.team]
        .concat(resultRows(record).map(([term, value]) => `${term} ${value}`))
        .concat(record.provenance)
        .join(". "),
    );

    const showAt = (clientX, clientY) => {
      fillTooltip(tooltip, record);
      positionTooltip(tooltip, clientX, clientY);
    };
    node.addEventListener("pointerenter", (event) => showAt(event.clientX, event.clientY));
    node.addEventListener("pointermove", (event) => {
      if (!tooltip.hidden) positionTooltip(tooltip, event.clientX, event.clientY);
    });
    node.addEventListener("pointerleave", () => {
      if (document.activeElement !== node) tooltip.hidden = true;
    });
    node.addEventListener("focus", () => {
      const bounds = node.getBoundingClientRect();
      showAt(bounds.left + bounds.width / 2, bounds.top);
    });
    node.addEventListener("blur", () => {
      tooltip.hidden = true;
    });
    node.addEventListener("keydown", (event) => {
      if (event.key === "Escape") tooltip.hidden = true;
    });
    return node;
  };

  const renderBarChart = (mount, records) => {
    const width = 1180;
    const left = 300;
    const plotWidth = 620;
    const right = left + plotWidth;
    const top = 88;
    const rowHeight = 54;
    const barHeight = 22;
    const bottom = top + records.length * rowHeight;
    const height = bottom + 40;
    const svg = chartFrame(mount, width, height);
    const [barColor] = teamColor(0);
    const patternId = `late-bars-${mount.dataset.chartState || "chart"}`;
    latePattern(svg, patternId, barColor);
    addAxis(svg, { left, top, plotWidth, bottom, ticks: [0, 20, 40, 60, 80, 100], scale: "linear" });

    records.forEach((record, index) => {
      const y = top + 12 + index * rowHeight;
      const barWidth = plotWidth * scaleQuantile(record.quantile);
      if (index % 2 === 0) {
        svg.append(
          svgNode("rect", {
            class: "chart-row-band",
            x: 14,
            y: y - 12,
            width: width - 28,
            height: rowHeight - 6,
          }),
        );
      }
      const bar = bindRecordTooltip(
        svgNode("rect", {
          x: left,
          y,
          width: Math.max(2, barWidth),
          height: barHeight,
          rx: 4,
          fill: record.official ? barColor : `url(#${patternId})`,
          ...(record.official ? {} : { stroke: barColor, "stroke-width": 1 }),
        }),
        record,
      );
      // Keep the value off the rank column: park it inside the bar once it is long.
      const valueInside = barWidth >= 78;
      svg.append(
        svgNode(
          "text",
          { class: "chart-row-title", x: 24, y: y + 4 },
          truncateLabel(record.competition),
        ),
        svgNode(
          "text",
          { class: "chart-row-meta", x: 24, y: y + 22 },
          truncateLabel(`${record.team} · ${scoreSourceLabel(record)} ${record.score}`, 41),
        ),
        bar,
        svgNode(
          "text",
          {
            class:
              valueInside && record.official
                ? "chart-bar-value chart-bar-value-inside"
                : "chart-bar-value",
            x: valueInside ? left + barWidth - 8 : left + barWidth + 8,
            y: y + 16,
            "text-anchor": valueInside ? "end" : "start",
          },
          `Q ${record.quantile.toFixed(2)}`,
        ),
        svgNode(
          "text",
          { class: "chart-rank-label", x: right + 20, y: y + 6 },
          `${rankSourceLabel(record)} · #${record.rank.toLocaleString()} / ` +
            record.teamCount.toLocaleString(),
        ),
        svgNode(
          "text",
          { class: "chart-row-meta", x: right + 20, y: y + 24 },
          `Top ${record.topPercent.toFixed(2)}% · ${scoreSourceLabel(record)}`,
        ),
      );
    });
  };

  const pointOffsets = (count, rowHeight) => {
    if (count <= 1) return [0];
    const span = Math.min(rowHeight - 28, (count - 1) * 24);
    return Array.from({ length: count }, (_, index) => -span / 2 + (span * index) / (count - 1));
  };

  const renderScatterChart = (mount, records, teamColors) => {
    const grouped = new Map();
    records.forEach((record) => {
      if (!grouped.has(record.competition)) grouped.set(record.competition, []);
      grouped.get(record.competition).push(record);
    });
    const present = new Set(records.map((record) => record.team));
    const teams = [...teamColors.keys()].filter((team) => present.has(team));
    const width = 1180;
    const left = 300;
    const plotWidth = 840;
    const top = 88;
    const rowLayouts = [...grouped.entries()].map(([competition, groupRecords]) => ({
      competition,
      records: groupRecords,
      height: Math.max(78, 40 + groupRecords.length * 24),
    }));
    let cursor = top;
    rowLayouts.forEach((row) => {
      row.top = cursor;
      row.center = cursor + row.height / 2;
      cursor += row.height;
    });
    const plotBottom = cursor;
    const legendColumns = 4;
    const legendHeight = 64 + Math.ceil(teams.length / legendColumns) * 28;
    const height = plotBottom + legendHeight;
    const svg = chartFrame(mount, width, height);
    const scale = mount.dataset.chartScale || "linear";
    addAxis(svg, {
      left,
      top,
      plotWidth,
      bottom: plotBottom,
      ticks: scale === "lens" ? [0, 40, 80, 90, 95, 97, 98, 99, 100] : [0, 20, 40, 60, 80, 100],
      scale,
    });

    rowLayouts.forEach((row, rowIndex) => {
      if (rowIndex % 2 === 0) {
        svg.append(
          svgNode("rect", {
            class: "chart-row-band",
            x: 14,
            y: row.top + 4,
            width: width - 28,
            height: row.height - 8,
          }),
        );
      }
      svg.append(
        svgNode(
          "text",
          { class: "chart-row-title", x: 24, y: row.center - 3 },
          truncateLabel(row.competition),
        ),
        svgNode(
          "text",
          { class: "chart-row-meta", x: 24, y: row.center + 17 },
          `${row.records.length} account result${row.records.length === 1 ? "" : "s"}`,
        ),
        svgNode("line", {
          class: "chart-row-line",
          x1: left,
          y1: row.center,
          x2: left + plotWidth,
          y2: row.center,
        }),
      );

      const offsets = pointOffsets(row.records.length, row.height);
      row.records.forEach((record, index) => {
        const x = left + plotWidth * scaleQuantile(record.quantile, scale);
        const y = row.center + offsets[index];
        const [color, ink] = teamColors.get(record.team) || TEAM_COLORS[0];
        const marker = bindRecordTooltip(
          svgNode("circle", {
            class: record.official ? "chart-mark-official" : "chart-mark-estimate",
            cx: x,
            cy: y,
            r: 9,
            ...(record.official ? { fill: color } : { stroke: color }),
          }),
          record,
        );
        marker.dataset.team = record.team;
        svg.append(
          svgNode("circle", {
            class: "chart-team-highlight-ring",
            cx: x,
            cy: y,
            r: 14,
            "data-team": record.team,
            "aria-hidden": "true",
          }),
          marker,
          svgNode(
            "text",
            {
              class: "chart-point-initial",
              x,
              y,
              fill: record.official ? ink : color,
            },
            teamInitial(record.team),
          ),
        );
      });
    });

    const legendTop = plotBottom + 26;
    const [sampleColor] = TEAM_COLORS[0];
    svg.append(
      svgNode("circle", {
        class: "chart-mark-official",
        cx: 28,
        cy: legendTop,
        r: 6,
        fill: sampleColor,
      }),
      svgNode("text", { class: "chart-legend-label", x: 42, y: legendTop + 4 }, "Official rank"),
      svgNode("circle", {
        class: "chart-mark-estimate",
        cx: 170,
        cy: legendTop,
        r: 6,
        stroke: sampleColor,
      }),
      svgNode("text", { class: "chart-legend-label", x: 184, y: legendTop + 4 }, "Late estimate*"),
    );
    teams.forEach((team, index) => {
      const x = 28 + (index % legendColumns) * 280;
      const y = legendTop + 34 + Math.floor(index / legendColumns) * 28;
      const [color, ink] = teamColors.get(team) || TEAM_COLORS[0];
      const control = svgNode("g", {
        class: "chart-legend-control",
        role: "button",
        tabindex: 0,
        "aria-label": `Highlight all ${team} results`,
        "aria-pressed": "false",
        "data-team": team,
      });
      control.append(
        svgNode("circle", { cx: x, cy: y, r: 8, fill: color }),
        svgNode("text", { class: "chart-legend-initial", x, y, fill: ink }, teamInitial(team)),
        svgNode("text", { class: "chart-legend-label", x: x + 15, y: y + 4 }, truncateLabel(team, 28)),
      );
      svg.append(control);
    });
  };

  let highlightedTeam = "";

  /** Highlight every mark of one account, touching only the two teams involved. */
  const bindLegendControls = () => {
    // Each node kind answers to its own class, so they are registered separately.
    const byTeam = new Map();
    const register = (team, node, className) => {
      if (!team) return;
      if (!byTeam.has(team)) byTeam.set(team, []);
      byTeam.get(team).push([node, className]);
    };
    document
      .querySelectorAll(".chart-team-highlight-ring[data-team]")
      .forEach((ring) => register(ring.dataset.team, ring, "chart-team-highlighted"));
    document
      .querySelectorAll(".chart-legend-control")
      .forEach((control) => register(control.dataset.team, control, "chart-legend-selected"));

    const paint = (team, selected) => {
      (byTeam.get(team) || []).forEach(([node, className]) => {
        node.classList.toggle(className, selected);
        if (node.hasAttribute("aria-pressed")) {
          node.setAttribute("aria-pressed", String(selected));
        }
      });
    };
    const toggle = (team) => {
      if (!team) return;
      paint(highlightedTeam, false);
      highlightedTeam = highlightedTeam === team ? "" : team;
      paint(highlightedTeam, true);
    };

    document.querySelectorAll(".chart-legend-control").forEach((control) => {
      control.addEventListener("click", () => toggle(control.dataset.team || ""));
      control.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        toggle(control.dataset.team || "");
      });
    });
  };

  const renderCharts = () => {
    const chartData = new Map();
    const charts = [...document.querySelectorAll(".chart-mount")].map((mount) => [
      mount,
      readRecords(mount, chartData),
    ]);
    const allTeams = [
      ...new Set(charts.flatMap(([, records]) => records.map((record) => record.team))),
    ]
      .filter(Boolean)
      .sort((left, right) => left.localeCompare(right, "zh-CN"));
    const teamColors = new Map(allTeams.map((team, index) => [team, teamColor(index)]));

    charts.forEach(([mount, records]) => {
      if (!records.length) return;
      if (mount.dataset.chartType === "bar") renderBarChart(mount, records);
      if (mount.dataset.chartType === "scatter") renderScatterChart(mount, records, teamColors);
    });
    bindLegendControls();
  };

  const exported = {
    pointOffsets,
    formatResultTime,
    rankSourceLabel,
    scaleQuantile,
    scoreSourceLabel,
    teamColor,
    teamInitial,
    truncateLabel,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  if (typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderCharts, { once: true });
  } else {
    renderCharts();
  }
})();
