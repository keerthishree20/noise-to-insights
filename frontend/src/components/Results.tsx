import type { AnalysisResult, SegmentResult } from "../types";
import { SegmentCrosstab } from "./SegmentCrosstab";
import { ThemeBars } from "./ThemeBars";

function formatP(p: number) {
  return p < 0.001 ? p.toExponential(1) : p.toFixed(3);
}

function SegmentCard({
  result,
  themeOrder,
}: {
  result: SegmentResult;
  themeOrder: string[];
}) {
  return (
    <div className="card">
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          flexWrap: "wrap",
          marginBottom: 12,
        }}
      >
        <h3>{result.segment}</h3>
        {result.testable ? (
          <>
            <span className={result.significant ? "pill pill-sig" : "pill"}>
              {result.significant ? "significant" : "not significant"}
            </span>
            <span className="small muted">
              p = {formatP(result.p_value!)} · Cramér's V ={" "}
              {result.cramers_v!.toFixed(2)} · n = {result.n}
            </span>
          </>
        ) : (
          <span className="pill">not testable</span>
        )}
      </div>

      <SegmentCrosstab result={result} themeOrder={themeOrder} />

      {result.testable && (
        <p className="small muted" style={{ marginTop: 10 }}>
          {result.significant
            ? "Themes are distributed differently across these groups by more than chance, after correcting for the number of comparisons."
            : "No difference beyond what the number of comparisons would produce by chance."}
        </p>
      )}
    </div>
  );
}

export function Results({ result }: { result: AnalysisResult }) {
  const significant = result.segments.filter((s) => s.significant);
  const themeOrder = result.themes.map((t) => t.label);

  return (
    <div className="stack">
      {result.narrative && (
        <div className="card">
          <h2 style={{ marginBottom: 10 }}>Readout</h2>
          {result.narrative
            .split(/\n{2,}/)
            .filter(Boolean)
            .map((paragraph, i) => (
              <p key={i} style={{ marginBottom: 10 }}>
                {paragraph}
              </p>
            ))}
        </div>
      )}

      <div className="card">
        <h2>Themes</h2>
        <p className="small muted" style={{ margin: "4px 0 16px" }}>
          {result.response_count} responses from “{result.text_column}”, grouped into{" "}
          {result.themes.length}{" "}
          {result.clustered
            ? "clusters and named"
            : "themes assigned directly (too few responses to cluster)"}
          .
        </p>

        <ThemeBars themes={result.themes} />

        <div style={{ marginTop: 18 }} className="stack">
          {result.themes.map((theme) => (
            <details key={theme.label}>
              <summary>
                {theme.label} — {theme.summary}
              </summary>
              <div style={{ padding: "8px 0 4px 14px" }}>
                {theme.keywords.length > 0 && (
                  <p className="small muted">
                    Distinctive terms: {theme.keywords.join(", ")}
                  </p>
                )}
                {theme.exemplars.map((quote, i) => (
                  <blockquote key={i} className="small">
                    {quote}
                  </blockquote>
                ))}
              </div>
            </details>
          ))}
        </div>
      </div>

      {result.segments.length > 0 && (
        <>
          <div>
            <h2>Across segments</h2>
            <p className="small muted" style={{ marginTop: 4 }}>
              {significant.length} of {result.segments.length} comparisons held up
              after Benjamini–Hochberg correction. Each column shows how that group’s
              answers split across the themes.
            </p>
          </div>
          {result.segments.map((segment) => (
            <SegmentCard
              key={segment.segment}
              result={segment}
              themeOrder={themeOrder}
            />
          ))}
        </>
      )}
    </div>
  );
}
