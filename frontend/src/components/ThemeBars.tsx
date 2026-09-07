import type { Theme } from "../types";

/**
 * Share of responses per theme.
 *
 * One series, so there is no legend and no categorical palette: every bar is
 * the same hue and the axis carries the comparison. Bars are sorted by size,
 * which is what makes the ranking readable at a glance.
 */
export function ThemeBars({ themes }: { themes: Theme[] }) {
  if (themes.length === 0) return null;

  // Scale to the largest theme rather than to 100%, so small differences among
  // a dozen themes stay visible instead of collapsing into stubs.
  const max = Math.max(...themes.map((t) => t.share));

  return (
    <div className="bars">
      {themes.map((theme) => (
        <div className="bar-row" key={theme.label}>
          <span className="bar-label" title={theme.label}>
            {theme.label}
          </span>
          <div
            className="bar-track"
            role="img"
            aria-label={`${theme.label}: ${theme.share}% of responses (${theme.size})`}
          >
            <div
              className="bar-fill"
              style={{ width: `${max > 0 ? (theme.share / max) * 100 : 0}%` }}
            />
          </div>
          <span className="bar-value">
            {theme.share}%
            <span className="muted"> · {theme.size}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
