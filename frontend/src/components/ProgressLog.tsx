import { useEffect, useRef } from "react";

export interface LogLine {
  stage: string;
  message: string;
}

/**
 * The stages of a run, as they happen.
 *
 * A run does real work -- clustering, a model call per group, a chi-square per
 * segment -- and can take a while. Naming the stage that is currently running
 * is the difference between "working" and "hung".
 */
export function ProgressLog({ lines, partial }: { lines: LogLine[]; partial: string }) {
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [lines.length, partial]);

  if (lines.length === 0 && !partial) return null;

  return (
    <div className="card">
      <div className="log" aria-live="polite">
        {lines.map((line, i) => (
          <div key={i}>
            <span className="log-stage">{line.stage}</span>
            {line.message}
          </div>
        ))}
        {partial && (
          <div style={{ marginTop: 8 }} className="secondary">
            {partial}
          </div>
        )}
        <div ref={end} />
      </div>
    </div>
  );
}
