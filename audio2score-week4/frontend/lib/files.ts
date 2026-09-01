export const ALLOWED_EXTENSIONS = [
  ".wav",
  ".mp3",
  ".m4a",
  ".flac",
  ".mid",
  ".midi",
] as const;

export const MAX_UPLOAD_MB = 25;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

export type FileCheck =
  | { ok: true; midi: boolean }
  | { ok: false; reason: "type" | "size" };

export function fileExtension(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

export function isMidiFilename(name: string): boolean {
  const ext = fileExtension(name);
  return ext === ".mid" || ext === ".midi";
}

export function validateRecording(file: File | null): FileCheck {
  if (!file) return { ok: false, reason: "type" };
  const ext = fileExtension(file.name);
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
    return { ok: false, reason: "type" };
  }
  if (file.size > MAX_UPLOAD_BYTES) return { ok: false, reason: "size" };
  return { ok: true, midi: isMidiFilename(file.name) };
}

export function friendlyUploadError(error: unknown): string {
  const raw =
    error && typeof error === "object" && "message" in error
      ? String((error as { message: unknown }).message)
      : typeof error === "string"
        ? error
        : "";
  const text = raw.toLowerCase();
  if (text.includes("invalid file type") || text.includes("invalid content type")) {
    return "This file type isn’t supported. Choose MP3, WAV, M4A, FLAC, or MIDI.";
  }
  if (text.includes("too large")) {
    return `This recording is too large. Please choose a file under ${MAX_UPLOAD_MB} MB.`;
  }
  if (text.includes("network") || text.includes("failed to fetch")) {
    return "Something went wrong. Check your connection and try again.";
  }
  return "We couldn’t send your recording. Please try again.";
}
