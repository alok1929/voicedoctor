"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Music, Trash2, Upload } from "lucide-react";
import { Button } from "../../components/ui";
import { InsetList, InsetRow } from "../../components/ui/InsetList";
import { ICON_SIZE, ICON_STROKE } from "../../lib/icons";
import {
  EVALS_API,
  evalsAuthHeaders,
  fetchAudioBlobUrl,
  type LibraryGrouped,
  type LibraryItem,
} from "../../lib/evalsApi";
import PreviewButton from "../evals/components/PreviewButton";

type Category = keyof LibraryGrouped;

const SECTIONS: {
  key: Category;
  title: string;
  caption: string;
  successTarget: string;
}[] = [
  {
    key: "ambient",
    title: "Ambient sounds",
    caption: "Background noise mixed into the tester's outgoing audio during calls.",
    successTarget: "Ambient noise",
  },
  {
    key: "barge_in",
    title: "Barge-in sounds",
    caption: "Sound clips played when the tester interrupts the agent mid-turn.",
    successTarget: "Barge-in",
  },
  {
    key: "other",
    title: "Others",
    caption: "Caller reaction sounds — appear under Barge-in when configuring calls.",
    successTarget: "Caller reactions",
  },
];

const EMPTY_LIBRARY: LibraryGrouped = { ambient: [], barge_in: [], other: [] };

export default function LibraryPage() {
  const [library, setLibrary] = useState<LibraryGrouped>(EMPTY_LIBRARY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState<Category | null>(null);
  const [labels, setLabels] = useState<Record<Category, string>>({
    ambient: "",
    barge_in: "",
    other: "",
  });
  const [files, setFiles] = useState<Record<Category, File | null>>({
    ambient: null,
    barge_in: null,
    other: null,
  });
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const blobUrlRef = useRef<string | null>(null);

  const stopPreview = useCallback(() => {
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current = null;
    }
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }
    setPreviewingId(null);
  }, []);

  const loadLibrary = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${EVALS_API}/api/library`, { headers: evalsAuthHeaders() });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || res.statusText);
      }
      const data = await res.json();
      setLibrary({ ...EMPTY_LIBRARY, ...(data.items || {}) });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLibrary();
    return () => stopPreview();
  }, [loadLibrary, stopPreview]);

  useEffect(() => {
    if (!successMsg) return;
    const t = setTimeout(() => setSuccessMsg(null), 5000);
    return () => clearTimeout(t);
  }, [successMsg]);

  async function handleUpload(category: Category) {
    const label = labels[category].trim();
    const file = files[category];
    if (!label || !file) {
      setError("Enter a name and choose an MP3 file.");
      return;
    }
    setUploading(category);
    setError("");
    try {
      const body = new FormData();
      body.append("category", category);
      body.append("label", label);
      body.append("file", file);
      const res = await fetch(`${EVALS_API}/api/library`, {
        method: "POST",
        headers: evalsAuthHeaders(),
        body,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      const section = SECTIONS.find((s) => s.key === category);
      setSuccessMsg(
        `Uploaded. This sound will automatically appear in the ${section?.successTarget ?? "configure"} section when configuring calls.`
      );
      setLabels((p) => ({ ...p, [category]: "" }));
      setFiles((p) => ({ ...p, [category]: null }));
      await loadLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(null);
    }
  }

  async function handleDelete(item: LibraryItem) {
    if (!confirm(`Delete "${item.label}"?`)) return;
    setError("");
    try {
      const res = await fetch(`${EVALS_API}/api/library/${item.id}`, {
        method: "DELETE",
        headers: evalsAuthHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      if (previewingId === item.id) stopPreview();
      await loadLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function togglePreview(item: LibraryItem) {
    if (previewingId === item.id) {
      stopPreview();
      return;
    }
    stopPreview();
    try {
      const url = await fetchAudioBlobUrl(`/api/library-preview/${item.id}`);
      blobUrlRef.current = url;
      const audio = new Audio(url);
      previewAudioRef.current = audio;
      setPreviewingId(item.id);
      audio.play().catch(() => stopPreview());
      audio.onended = () => stopPreview();
    } catch {
      setError("Could not play preview.");
      stopPreview();
    }
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header__row">
          <Music size={ICON_SIZE} strokeWidth={ICON_STROKE} />
          <h1 className="page-title">Library</h1>
        </div>
        <p className="page-subtitle">
          Upload MP3 sounds for ambient noise, barge-in, and caller reactions. Uploaded sounds appear automatically when you configure calls in Run Eval.
        </p>
      </div>

      {successMsg && (
        <div className="library-success" role="status">
          <strong>Uploaded.</strong> {successMsg.replace(/^Uploaded\.\s*/, "")}
        </div>
      )}
      {error && <p className="form-error">{error}</p>}

      {loading ? (
        <p className="text-caption">Loading library…</p>
      ) : (
        SECTIONS.map((section) => (
          <section key={section.key} className="library-section">
            <h2 className="text-heading">{section.title}</h2>
            <p className="text-caption" style={{ marginBottom: "var(--space-4)" }}>
              {section.caption}
            </p>

            {library[section.key].length > 0 ? (
              <InsetList>
                {library[section.key].map((item) => (
                  <InsetRow
                    key={item.id}
                    trailing={
                      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
                        <PreviewButton
                          playing={previewingId === item.id}
                          onClick={() => togglePreview(item)}
                          label="Preview"
                        />
                        <button
                          type="button"
                          className="icon-btn"
                          aria-label={`Delete ${item.label}`}
                          onClick={() => handleDelete(item)}
                        >
                          <Trash2 size={16} strokeWidth={ICON_STROKE} />
                        </button>
                      </div>
                    }
                  >
                    <span className="text-body">{item.label}</span>
                  </InsetRow>
                ))}
              </InsetList>
            ) : (
              <p className="text-caption" style={{ marginBottom: "var(--space-3)" }}>
                No uploads yet.
              </p>
            )}

            <div className="library-upload">
              <input
                type="text"
                className="form-input"
                placeholder="Sound name"
                value={labels[section.key]}
                onChange={(e) => setLabels((p) => ({ ...p, [section.key]: e.target.value }))}
              />
              <label className="library-file-label">
                <input
                  type="file"
                  accept="audio/mpeg,.mp3"
                  className="library-file-input"
                  onChange={(e) =>
                    setFiles((p) => ({
                      ...p,
                      [section.key]: e.target.files?.[0] ?? null,
                    }))
                  }
                />
                <span className="text-caption">
                  {files[section.key]?.name ?? "Choose MP3"}
                </span>
              </label>
              <Button
                variant="primary"
                size="sm"
                disabled={uploading === section.key}
                onClick={() => handleUpload(section.key)}
              >
                <Upload size={14} strokeWidth={ICON_STROKE} />
                {uploading === section.key ? "Uploading…" : "Upload"}
              </Button>
            </div>
          </section>
        ))
      )}
    </div>
  );
}
