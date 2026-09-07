import type { Profile } from "../types";

/**
 * Choose what to analyse.
 *
 * Both fields arrive pre-filled from profiling, so the common path is to press
 * Run without touching anything. Only columns profiling classed as free text
 * are offerable -- themes over a categorical column would be meaningless.
 */
export function AnalysisSetup({
  profile,
  textColumn,
  segments,
  onTextColumn,
  onSegments,
  onRun,
  running,
}: {
  profile: Profile;
  textColumn: string | null;
  segments: string[];
  onTextColumn: (column: string) => void;
  onSegments: (segments: string[]) => void;
  onRun: () => void;
  running: boolean;
}) {
  const toggle = (name: string) =>
    onSegments(
      segments.includes(name) ? segments.filter((s) => s !== name) : [...segments, name],
    );

  if (profile.text_columns.length === 0) {
    return (
      <div className="banner banner-note">
        No free-text column was found in this file. This tool themes open-ended
        answers, so there is nothing here for it to read.
      </div>
    );
  }

  return (
    <div className="card stack">
      <div>
        <label htmlFor="text-column">Open-text column to theme</label>
        <select
          id="text-column"
          value={textColumn ?? ""}
          onChange={(e) => onTextColumn(e.target.value)}
        >
          {profile.text_columns.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      {profile.segment_columns.length > 0 && (
        <div>
          <label>Compare across</label>
          <div className="checks">
            {profile.segment_columns.map((name) => (
              <label key={name}>
                <input
                  type="checkbox"
                  checked={segments.includes(name)}
                  onChange={() => toggle(name)}
                />
                {name}
              </label>
            ))}
          </div>
          <p className="small muted" style={{ marginTop: 6 }}>
            At most six are tested, best-populated first. A comparison needs
            roughly five responses per theme-by-group cell to be valid — with a
            dozen themes that means a few hundred responses.
          </p>
        </div>
      )}

      <div>
        <button className="btn" onClick={onRun} disabled={running || !textColumn}>
          {running ? "Analysing…" : "Run analysis"}
        </button>
      </div>
    </div>
  );
}
