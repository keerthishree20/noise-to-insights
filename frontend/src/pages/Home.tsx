import { useState } from "react";

import { api } from "../api/client";
import { UploadDropzone } from "../components/UploadDropzone";

export function Home({ onUploaded }: { onUploaded: (id: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.upload(file);
      onUploaded(id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div>
        <h1>Noise to Insights</h1>
        <p className="secondary" style={{ marginTop: 6, maxWidth: 620 }}>
          Upload a survey export. Open-ended answers are grouped by similarity,
          each group is named as a theme, and every theme is tested against your
          respondent segments — so “pricing came up a lot” becomes “pricing came
          up three times more among trial users, and that gap is not noise.”
        </p>
      </div>

      <UploadDropzone onFile={upload} busy={busy} />

      {error && <div className="banner">{error}</div>}

      <div className="card">
        <h3 style={{ marginBottom: 8 }}>What it does with the file</h3>
        <ol className="small secondary" style={{ margin: 0, paddingLeft: 18 }}>
          <li>
            Classifies every column as free text, a segment, a number or an
            identifier — you don’t have to say which question was open-ended.
          </li>
          <li>
            Clusters the open-text answers by similarity, so each theme is a real
            set of responses you can open and read rather than a summary you have
            to trust.
          </li>
          <li>
            Names each cluster from the respondents’ own vocabulary.
          </li>
          <li>
            Crosstabs themes against each segment and applies a
            Benjamini–Hochberg correction, because testing a dozen themes against
            six segments would otherwise manufacture findings.
          </li>
        </ol>
      </div>
    </div>
  );
}
