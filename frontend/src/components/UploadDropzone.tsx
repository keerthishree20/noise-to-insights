import { useRef, useState } from "react";

export function UploadDropzone({
  onFile,
  busy,
}: {
  onFile: (file: File) => void;
  busy: boolean;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  return (
    <div
      className="dropzone"
      data-over={over}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const file = e.dataTransfer.files?.[0];
        if (file && !busy) onFile(file);
      }}
    >
      <p style={{ fontWeight: 560 }}>
        {busy ? "Reading the file…" : "Drop a survey export here"}
      </p>
      <p className="small muted" style={{ margin: "4px 0 14px" }}>
        CSV, TSV or Excel. Nothing leaves this machine except the response text
        sent for theming.
      </p>

      <button
        className="btn"
        disabled={busy}
        onClick={() => input.current?.click()}
        type="button"
      >
        Choose a file
      </button>

      <input
        ref={input}
        type="file"
        accept=".csv,.tsv,.txt,.xlsx,.xls,.xlsm"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          // Reset so re-selecting the same file fires change again.
          e.target.value = "";
        }}
      />
    </div>
  );
}
