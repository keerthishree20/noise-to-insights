import { useCallback, useEffect, useRef, useState } from "react";

import { api, streamAnalysis } from "../api/client";
import { AnalysisSetup } from "../components/AnalysisSetup";
import { ProgressLog, type LogLine } from "../components/ProgressLog";
import { Results } from "../components/Results";
import type { AnalysisResult, DatasetDetail } from "../types";

export function DatasetView({
  datasetId,
  onDeleted,
}: {
  datasetId: string;
  onDeleted: () => void;
}) {
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [textColumn, setTextColumn] = useState<string | null>(null);
  const [segments, setSegments] = useState<string[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);

  const [lines, setLines] = useState<LogLine[]>([]);
  const [narrative, setNarrative] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Held so an in-flight stream is closed when the user navigates away.
  const closeStream = useRef<(() => void) | null>(null);

  useEffect(() => {
    let cancelled = false;

    setDataset(null);
    setResult(null);
    setLines([]);
    setNarrative("");
    setError(null);

    api
      .getDataset(datasetId)
      .then((detail) => {
        if (cancelled) return;
        setDataset(detail);
        setResult(detail.result);
        setTextColumn(detail.result?.text_column ?? detail.profile?.suggested_text_column ?? null);
        setSegments(detail.profile?.segment_columns ?? []);
      })
      .catch((e: Error) => !cancelled && setError(e.message));

    return () => {
      cancelled = true;
      closeStream.current?.();
      closeStream.current = null;
    };
  }, [datasetId]);

  const run = useCallback(() => {
    setRunning(true);
    setError(null);
    setResult(null);
    setLines([]);
    setNarrative("");

    closeStream.current = streamAnalysis(
      datasetId,
      { textColumn, segments },
      (event) => {
        switch (event.type) {
          case "progress":
            setLines((prev) => [...prev, { stage: event.stage, message: event.message }]);
            break;
          case "narrative":
            setNarrative((prev) => prev + event.text);
            break;
          case "result":
            setResult(event.result);
            setRunning(false);
            break;
          case "error":
            setError(event.message);
            setRunning(false);
            break;
        }
      },
    );
  }, [datasetId, textColumn, segments]);

  const remove = async () => {
    if (!confirm(`Delete “${dataset?.name}” and its analysis?`)) return;
    await api.deleteDataset(datasetId);
    onDeleted();
  };

  if (error && !dataset) return <div className="banner">{error}</div>;
  if (!dataset) return <p className="muted">Loading…</p>;

  return (
    <div className="stack">
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1>{dataset.name}</h1>
          <p className="small muted">
            {dataset.row_count.toLocaleString()} rows ·{" "}
            {dataset.profile?.columns.length ?? 0} columns
          </p>
        </div>
        <button className="btn btn-quiet" onClick={remove}>
          Delete
        </button>
      </div>

      {dataset.profile && (
        <AnalysisSetup
          profile={dataset.profile}
          textColumn={textColumn}
          segments={segments}
          onTextColumn={setTextColumn}
          onSegments={setSegments}
          onRun={run}
          running={running}
        />
      )}

      {error && <div className="banner">{error}</div>}

      {running && <ProgressLog lines={lines} partial={narrative} />}

      {result && <Results result={result} />}
    </div>
  );
}
