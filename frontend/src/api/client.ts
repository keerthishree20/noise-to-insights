import type {
  DatasetDetail,
  DatasetSummary,
  StreamEvent,
  UploadResponse,
} from "../types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    // fetch only rejects on network-level failure, where the browser gives us
    // nothing useful ("Failed to fetch"). The likely causes are a backend that
    // isn't running or an origin the backend's CORS policy doesn't allow.
    throw new Error(
      `Could not reach the API at ${BASE}. Check that the backend is running, ` +
        `and that you opened this page on the origin it allows.`,
    );
  }

  if (!res.ok) {
    // FastAPI puts human-readable messages in `detail`; surface those rather
    // than a bare status code, since they are written for the end user.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body -- keep the status line */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  health: () =>
    request<{ status: string; llm_configured: boolean; model: string }>("/api/health"),

  listDatasets: () => request<DatasetSummary[]>("/api/datasets"),

  getDataset: (id: string) => request<DatasetDetail>(`/api/datasets/${id}`),

  deleteDataset: (id: string) =>
    request<void>(`/api/datasets/${id}`, { method: "DELETE" }),

  getResponses: (id: string, column: string, limit = 200) =>
    request<{ column: string; total: number; responses: string[] }>(
      `/api/datasets/${id}/responses?column=${encodeURIComponent(column)}&limit=${limit}`,
    ),

  upload(file: File): Promise<UploadResponse> {
    const body = new FormData();
    body.append("file", file);
    return request<UploadResponse>("/api/datasets", { method: "POST", body });
  },
};

/**
 * Open the analysis stream.
 *
 * `EventSource` can only issue GETs and cannot be aborted mid-flight with an
 * AbortController, so the returned function closes it. Every event type the
 * backend emits is registered by name, because the server sets `event:` on each
 * frame -- a bare `onmessage` handler would never fire.
 */
export function streamAnalysis(
  datasetId: string,
  options: { textColumn?: string | null; segments?: string[] },
  onEvent: (event: StreamEvent) => void,
): () => void {
  const params = new URLSearchParams();
  if (options.textColumn) params.set("text_column", options.textColumn);
  for (const segment of options.segments ?? []) params.append("segments", segment);

  const query = params.toString();
  const source = new EventSource(
    `${BASE}/api/analysis/${datasetId}/stream${query ? `?${query}` : ""}`,
  );

  let finished = false;
  const close = () => {
    finished = true;
    source.close();
  };

  for (const name of ["progress", "narrative", "result", "error"] as const) {
    source.addEventListener(name, (event) => {
      const parsed = JSON.parse((event as MessageEvent).data) as StreamEvent;
      onEvent(parsed);
      // The stream is one-shot: nothing follows a result or an error.
      if (parsed.type === "result" || parsed.type === "error") close();
    });
  }

  source.onerror = () => {
    // EventSource reconnects by default. This stream cannot be resumed, so a
    // drop before the result is a real failure -- report it once and stop.
    if (finished) return;
    onEvent({ type: "error", message: "Lost the connection to the server." });
    close();
  };

  return close;
}
