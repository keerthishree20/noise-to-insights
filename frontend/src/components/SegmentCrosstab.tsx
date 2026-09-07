import type { SegmentResult } from "../types";

/* Sequential blue ramp, light -> dark, from the dataviz reference palette.
   A crosstab is continuous magnitude, so the lightest step is allowed to
   recede toward the surface. Ink flips to white once the fill is dark enough
   to need it. */
const RAMP = [
  { fill: "var(--ramp-100)", ink: "#0b0b0b" },
  { fill: "var(--ramp-200)", ink: "#0b0b0b" },
  { fill: "var(--ramp-300)", ink: "#0b0b0b" },
  { fill: "var(--ramp-450)", ink: "#ffffff" },
  { fill: "var(--ramp-550)", ink: "#ffffff" },
  { fill: "var(--ramp-700)", ink: "#ffffff" },
];

function step(percent: number, max: number) {
  if (max <= 0) return RAMP[0];
  const index = Math.min(RAMP.length - 1, Math.floor((percent / max) * RAMP.length));
  return RAMP[Math.max(0, index)];
}

/**
 * Themes crossed against one segment column.
 *
 * A heatmap rather than grouped bars: a segment can have up to thirty levels,
 * which no categorical palette can carry. The percentage is printed in every
 * cell, so colour is a second reading of the number rather than the only one.
 */
export function SegmentCrosstab({
  result,
  themeOrder,
}: {
  result: SegmentResult;
  /** Theme labels largest-first, so rows here line up with the bar chart above. */
  themeOrder: string[];
}) {
  const percentages = result.percentages;

  if (!percentages || Object.keys(percentages).length === 0) {
    return (
      <p className="small muted">
        {result.reason ?? "No crosstab available for this segment."}
      </p>
    );
  }

  // Columns are segment values; rows are themes. Column percentages sum to 100.
  const segmentValues = Object.keys(percentages);
  const present = new Set(
    segmentValues.flatMap((value) => Object.keys(percentages[value])),
  );
  // Follow the ranking from the bar chart; anything unexpected goes last.
  const themeLabels = [
    ...themeOrder.filter((label) => present.has(label)),
    ...[...present].filter((label) => !themeOrder.includes(label)),
  ];

  const max = Math.max(
    ...segmentValues.flatMap((v) => themeLabels.map((t) => percentages[v][t] ?? 0)),
  );

  return (
    <>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th scope="col">Theme</th>
              {segmentValues.map((value) => (
                <th scope="col" key={value}>
                  {value}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {themeLabels.map((theme) => (
              <tr key={theme}>
                <th scope="row" className="rowhead" title={theme}>
                  {theme}
                </th>
                {segmentValues.map((value) => {
                  const percent = percentages[value][theme] ?? 0;
                  const count = result.counts?.[value]?.[theme] ?? 0;
                  const tone = step(percent, max);
                  return (
                    <td key={value}>
                      <div
                        className="heat-cell"
                        style={{ background: tone.fill, color: tone.ink }}
                        title={`${theme} · ${value}: ${percent}% (${count} responses)`}
                      >
                        {percent}%
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="legend" style={{ marginTop: 10 }}>
        <span>0%</span>
        <div className="legend-swatches">
          {RAMP.map((tone) => (
            <div
              className="legend-swatch"
              key={tone.fill}
              style={{ background: tone.fill }}
            />
          ))}
        </div>
        <span>{max.toFixed(0)}%</span>
        <span style={{ marginLeft: 6 }}>share within each column</span>
      </div>
    </>
  );
}
