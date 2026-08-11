(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
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

  const teamColor = (index, total) => {
    const count = Math.max(1, Number(total) || 1);
    const hue = (156 + (Number(index) * 360) / count) % 360;
    const saturation = 72 + (Number(index) % 3) * 6;
    const lightness = 60 + (Math.floor(Number(index) / 3) % 2) * 7;
    return `hsl(${hue.toFixed(1)} ${saturation}% ${lightness}%)`;
  };

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

  const svgNode = (name, attributes = {}, text = "") => {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== "") node.textContent = text;
    return node;
  };

  const addTooltip = (node, value) => {
    node.append(svgNode("title", {}, value));
    return node;
  };

  const readRecords = (mount) =>
    [...mount.querySelectorAll(".chart-datum")].map((datum) => ({
      competition: datum.dataset.competition || "",
      team: datum.dataset.team || "",
      rank: Number(datum.dataset.rank),
      teamCount: Number(datum.dataset.teamCount),
      topPercent: Number(datum.dataset.topPercent),
      quantile: Number(datum.dataset.quantile),
      score: datum.dataset.score || "",
      resultKind: datum.dataset.resultKind || "",
      rankKind: datum.dataset.rankKind || "",
      scoreKind: datum.dataset.scoreKind || "",
      official: datum.dataset.isOfficial === "true",
      provenance: datum.dataset.provenance || "",
    }));

  const chartFrame = (mount, width, height) => {
    const wrapper = document.createElement("div");
    wrapper.className = "chart-scroll";
    const svg = svgNode("svg", {
      class: "quantile-chart-svg",
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-label": mount.dataset.chartTitle || "Kaggle quantile chart",
    });
    svg.append(
      svgNode("title", {}, mount.dataset.chartTitle || "Kaggle quantile chart"),
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
        svgNode("line", {
          class: "chart-grid-line",
          x1: x,
          y1: top,
          x2: x,
          y2: bottom,
        }),
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
          y: top - 45,
          "text-anchor": "middle",
        },
        scale === "lens" ? "Quantile (%) · high-percentile lens" : "Quantile (%)",
      ),
    );
  };

  const latePattern = (svg, id) => {
    const definitions = svgNode("defs");
    const pattern = svgNode("pattern", {
      id,
      width: 9,
      height: 9,
      patternUnits: "userSpaceOnUse",
    });
    pattern.append(
      svgNode("rect", { width: 9, height: 9, fill: "#b97b25" }),
      svgNode("path", {
        d: "M-2 2 L2 -2 M0 9 L9 0 M7 11 L11 7",
        stroke: "#ffd27e",
        "stroke-width": 2,
        opacity: 0.55,
      }),
    );
    definitions.append(pattern);
    svg.append(definitions);
  };

  const resultTooltip = (record) =>
    `${record.competition}\n${record.team}\n` +
    `${rankSourceLabel(record)} #${record.rank} / ${record.teamCount}\n` +
    `${scoreSourceLabel(record)} ${record.score}\n` +
    `Q${record.quantile.toFixed(2)} · Top ${record.topPercent.toFixed(2)}%\n` +
    record.provenance;

  let tooltipNode;

  const ensureTooltip = () => {
    if (tooltipNode) return tooltipNode;
    tooltipNode = document.createElement("div");
    tooltipNode.id = "chart-result-tooltip";
    tooltipNode.className = "chart-tooltip";
    tooltipNode.setAttribute("role", "tooltip");
    tooltipNode.hidden = true;
    document.body.append(tooltipNode);
    window.addEventListener(
      "scroll",
      () => {
        tooltipNode.hidden = true;
      },
      { capture: true, passive: true },
    );
    window.addEventListener("resize", () => {
      tooltipNode.hidden = true;
    });
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
    [
      [
        "Rank",
        `${rankSourceLabel(record)} · #${record.rank.toLocaleString()} / ${record.teamCount.toLocaleString()}`,
      ],
      ["Score", `${scoreSourceLabel(record)} · ${record.score}`],
      ["Quantile", `Q${record.quantile.toFixed(2)}`],
      ["Top", `${record.topPercent.toFixed(2)}%`],
    ].forEach(([term, value]) => {
      details.append(
        tooltipTextNode("dt", "", term),
        tooltipTextNode("dd", "", value),
      );
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
    node.setAttribute("aria-label", resultTooltip(record).replaceAll("\n", ". "));

    const showAt = (clientX, clientY) => {
      fillTooltip(tooltip, record);
      positionTooltip(tooltip, clientX, clientY);
    };
    node.addEventListener("pointerenter", (event) => {
      showAt(event.clientX, event.clientY);
    });
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
      if (event.key === "Escape") {
        tooltip.hidden = true;
      }
    });
    return node;
  };

  const renderBarChart = (mount, records) => {
    const width = 1180;
    const left = 310;
    const plotWidth = 610;
    const right = left + plotWidth;
    const top = 92;
    const rowHeight = 66;
    const bottom = top + records.length * rowHeight;
    const height = Math.max(280, bottom + 54);
    const svg = chartFrame(mount, width, height);
    const patternId = `late-bars-${mount.dataset.chartState || "chart"}`;
    latePattern(svg, patternId);
    addAxis(svg, {
      left,
      top,
      plotWidth,
      bottom,
      ticks: [0, 20, 40, 60, 80, 100],
      scale: "linear",
    });

    records.forEach((record, index) => {
      const y = top + 18 + index * rowHeight;
      const barWidth = plotWidth * scaleQuantile(record.quantile);
      if (index % 2 === 0) {
        svg.append(
          svgNode("rect", {
            class: "chart-row-band",
            x: 14,
            y: y - 13,
            width: width - 28,
            height: 56,
            rx: 5,
          }),
        );
      }
      svg.append(
        svgNode(
          "text",
          { class: "chart-row-title", x: 24, y: y + 5 },
          truncateLabel(record.competition),
        ),
        svgNode(
          "text",
          { class: "chart-row-meta", x: 24, y: y + 27 },
          truncateLabel(`${record.team} · ${scoreSourceLabel(record)} ${record.score}`, 41),
        ),
      );
      const bar = bindRecordTooltip(
        addTooltip(
          svgNode("rect", {
            x: left,
            y,
            width: Math.max(2, barWidth),
            height: 34,
            rx: 4,
            fill: record.official ? "#39e6b0" : `url(#${patternId})`,
            stroke: record.official ? "#82f3cf" : "#ffc563",
            "stroke-width": 1,
          }),
          resultTooltip(record),
        ),
        record,
      );
      const valueInside = barWidth >= 82;
      svg.append(
        bar,
        svgNode(
          "text",
          {
            class: valueInside ? "chart-bar-value chart-bar-value-inside" : "chart-bar-value",
            x: valueInside ? left + barWidth - 9 : left + barWidth + 9,
            y: y + 22,
            "text-anchor": valueInside ? "end" : "start",
          },
          `Q ${record.quantile.toFixed(2)}`,
        ),
        svgNode(
          "text",
          { class: "chart-rank-label", x: right + 20, y: y + 7 },
          `${rankSourceLabel(record)} · #${record.rank.toLocaleString()} / ` +
            record.teamCount.toLocaleString(),
        ),
        svgNode(
          "text",
          { class: "chart-row-meta", x: right + 20, y: y + 29 },
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
    const teams = [...new Set(records.map((record) => record.team))].sort((a, b) =>
      a.localeCompare(b, "zh-CN"),
    );
    const width = 1280;
    const left = 310;
    const plotWidth = 850;
    const top = 94;
    const rowLayouts = [...grouped.entries()].map(([competition, groupRecords]) => ({
      competition,
      records: groupRecords,
      height: Math.max(82, 44 + groupRecords.length * 24),
    }));
    let cursor = top;
    rowLayouts.forEach((row) => {
      row.top = cursor;
      row.center = cursor + row.height / 2;
      cursor += row.height;
    });
    const plotBottom = cursor;
    const legendColumns = 4;
    const legendRows = Math.ceil(teams.length / legendColumns);
    const legendHeight = 68 + legendRows * 30;
    const height = Math.max(330, plotBottom + legendHeight);
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
            rx: 5,
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
          { class: "chart-row-meta", x: 24, y: row.center + 19 },
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
        const color = teamColors.get(record.team) || "#39e6b0";
        const marker = bindRecordTooltip(
          addTooltip(
            svgNode("circle", {
              cx: x,
              cy: y,
              r: record.official ? 10 : 9.5,
              fill: record.official ? color : "#0c1a21",
              stroke: color,
              "stroke-width": record.official ? 2 : 3.5,
            }),
            resultTooltip(record),
          ),
          record,
        );
        const labelOnLeft = x > left + plotWidth - 120;
        svg.append(
          marker,
          svgNode(
            "text",
            {
              class: "chart-point-initial",
              x,
              y,
              fill: record.official ? "#061612" : color,
            },
            teamInitial(record.team),
          ),
          svgNode(
            "text",
            {
              class: "chart-point-label",
              x: labelOnLeft ? x - 15 : x + 15,
              y: y + 4,
              "text-anchor": labelOnLeft ? "end" : "start",
            },
            record.score,
          ),
        );
      });
    });

    const legendTop = plotBottom + 28;
    svg.append(
      svgNode("circle", { cx: 28, cy: legendTop, r: 6, fill: "#39e6b0", stroke: "#39e6b0" }),
      svgNode("text", { class: "chart-legend-label", x: 42, y: legendTop + 4 }, "Official rank"),
      svgNode("circle", { cx: 160, cy: legendTop, r: 6, fill: "#0c1a21", stroke: "#ffc563", "stroke-width": 3 }),
      svgNode("text", { class: "chart-legend-label", x: 174, y: legendTop + 4 }, "Late estimate*"),
    );
    teams.forEach((team, index) => {
      const column = index % legendColumns;
      const row = Math.floor(index / legendColumns);
      const x = 28 + column * 290;
      const y = legendTop + 36 + row * 30;
      const color = teamColors.get(team);
      svg.append(
        svgNode("circle", {
          cx: x,
          cy: y,
          r: 9,
          fill: color,
          stroke: "#dffaf2",
          "stroke-width": 1,
        }),
        svgNode("text", { class: "chart-legend-initial", x, y }, teamInitial(team)),
        svgNode("text", { class: "chart-legend-label", x: x + 16, y: y + 4 }, truncateLabel(team, 28)),
      );
    });
  };

  const renderCharts = () => {
    const mounts = [...document.querySelectorAll(".chart-mount")];
    const allTeams = [
      ...new Set(
        mounts.flatMap((mount) =>
          [...mount.querySelectorAll(".chart-datum")].map((datum) => datum.dataset.team || ""),
        ),
      ),
    ]
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b, "zh-CN"));
    const teamColors = new Map(
      allTeams.map((team, index) => [team, teamColor(index, allTeams.length)]),
    );

    mounts.forEach((mount) => {
      const records = readRecords(mount);
      if (!records.length) return;
      if (mount.dataset.chartType === "bar") renderBarChart(mount, records);
      if (mount.dataset.chartType === "scatter") renderScatterChart(mount, records, teamColors);
    });
  };

  const exported = {
    pointOffsets,
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
