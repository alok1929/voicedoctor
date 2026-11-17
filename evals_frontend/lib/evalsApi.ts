export const EVALS_API = process.env.NEXT_PUBLIC_EVALS_API || "http://localhost:7870";

export function getEvalsToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("evalra_token");
}

export function evalsAuthHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getEvalsToken();
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function fetchEvalsJson<T>(path: string): Promise<T | null> {
  const res = await fetch(`${EVALS_API}${path}`, { headers: evalsAuthHeaders() });
  if (!res.ok) return null;
  return res.json() as Promise<T>;
}

export async function fetchAudioBlobUrl(path: string): Promise<string> {
  const res = await fetch(`${EVALS_API}${path}`, { headers: evalsAuthHeaders() });
  if (!res.ok) throw new Error("Preview failed");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export type LibraryItem = {
  id: string;
  category: string;
  label: string;
  created_at?: string;
};

export type LibraryGrouped = {
  ambient: LibraryItem[];
  barge_in: LibraryItem[];
  other: LibraryItem[];
};
