import { useCallback, useEffect, useState } from "react";

import { api } from "./api/client";
import { DatasetView } from "./pages/DatasetView";
import { Home } from "./pages/Home";
import type { DatasetSummary } from "./types";

/** The selected dataset lives in the URL hash, so a result can be linked to and
 *  survives a refresh. Too small a surface to justify a router dependency. */
function useHashRoute(): [string | null, (id: string | null) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "") || null;
  const [id, setId] = useState<string | null>(read);

  useEffect(() => {
    const onChange = () => setId(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return [
    id,
    (next) => {
      window.location.hash = next ? `/${next}` : "";
      setId(next);
    },
  ];
}

export default function App() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selected, setSelected] = useHashRoute();
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const [offline, setOffline] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setDatasets(await api.listDatasets());
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    api
      .health()
      .then((h) => setLlmConfigured(h.llm_configured))
      .catch(() => setOffline(true));
  }, [refresh]);

  const onUploaded = async (id: string) => {
    await refresh();
    setSelected(id);
  };

  const onDeleted = async () => {
    setSelected(null);
    await refresh();
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <button
          className="btn"
          onClick={() => setSelected(null)}
          style={{ width: "100%" }}
        >
          New upload
        </button>

        <div style={{ minHeight: 0, display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="small muted" style={{ fontWeight: 560 }}>
            Datasets
          </span>

          {datasets.length === 0 ? (
            <p className="small muted">Nothing uploaded yet.</p>
          ) : (
            <div className="ds-list">
              {datasets.map((dataset) => (
                <button
                  key={dataset.id}
                  className="ds-item"
                  aria-current={dataset.id === selected}
                  onClick={() => setSelected(dataset.id)}
                >
                  <span className="ds-name">{dataset.name}</span>
                  <span className="small muted">
                    {dataset.row_count.toLocaleString()} rows
                    {dataset.analyzed ? " · analysed" : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div style={{ marginTop: "auto" }}>
          {offline && (
            <p className="small muted">
              Can’t reach the API. Is the backend running on port 8000?
            </p>
          )}
          {llmConfigured === false && (
            <p className="small muted">
              No API key configured — uploads and profiling work, but an analysis
              will stop at the theming step.
            </p>
          )}
        </div>
      </aside>

      <main className="main">
        {selected ? (
          <DatasetView datasetId={selected} onDeleted={onDeleted} />
        ) : (
          <Home onUploaded={onUploaded} />
        )}
      </main>
    </div>
  );
}
