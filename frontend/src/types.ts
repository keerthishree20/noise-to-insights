export type ColumnKind = "text" | "categorical" | "numeric" | "identifier" | "empty";

export interface Column {
  name: string;
  kind: ColumnKind;
  non_null: number;
  unique: number;
  avg_chars?: number;
  unique_ratio?: number;
  levels?: string[];
  mean?: number;
  min?: number;
  max?: number;
}

export interface Profile {
  columns: Column[];
  text_columns: string[];
  segment_columns: string[];
  suggested_text_column: string | null;
}

export interface Theme {
  label: string;
  summary: string;
  sentiment: string;
  size: number;
  share: number;
  keywords: string[];
  exemplars: string[];
  row_indices: number[];
}

export interface SegmentResult {
  segment: string;
  testable: boolean;
  reason?: string;
  p_value?: number;
  chi2?: number;
  cramers_v?: number;
  significant?: boolean;
  fdr_threshold?: number;
  n?: number;
  /** { segmentValue: { themeLabel: count } } */
  counts?: Record<string, Record<string, number>>;
  /** { segmentValue: { themeLabel: percent } } -- columns sum to 100 */
  percentages?: Record<string, Record<string, number>>;
}

export interface AnalysisResult {
  text_column: string;
  response_count: number;
  clustered: boolean;
  themes: Theme[];
  segments: SegmentResult[];
  narrative: string;
}

export interface DatasetSummary {
  id: string;
  name: string;
  row_count: number;
  created_at: string | null;
  analyzed: boolean;
}

export interface DatasetDetail {
  id: string;
  name: string;
  row_count: number;
  created_at: string | null;
  profile: Profile | null;
  result: AnalysisResult | null;
}

export interface UploadResponse {
  id: string;
  name: string;
  row_count: number;
  profile: Profile;
}

/** One frame off the SSE stream. */
export type StreamEvent =
  | { type: "progress"; stage: string; message: string; [k: string]: unknown }
  | { type: "narrative"; text: string }
  | { type: "result"; result: AnalysisResult }
  | { type: "error"; message: string };
