const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export { API_URL };

export type TranscriptionMode = "fast" | "quality";

export type Job = {
  job_id: string;
  status: string;
  filename?: string;
  content_type?: string;
  size_bytes?: number;
  progress?: number;
  error?: string | null;
  mode?: TranscriptionMode | string;
  result_available?: boolean;
  created_at?: string;
  updated_at?: string;
};

function detailMessage(data: unknown, fallback: string): string {
  if (!data || typeof data !== "object") return fallback;
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        typeof item === "object" && item && "msg" in item
          ? String((item as { msg: unknown }).msg)
          : String(item)
      )
      .join("; ");
  }
  return fallback;
}

export async function uploadAudio(
  file: File,
  onProgress?: (percent: number) => void,
  mode: TranscriptionMode = "fast"
): Promise<Job> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("file", file);
    formData.append("mode", mode);

    xhr.open("POST", `${API_URL}/upload`);

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return;
      onProgress(Math.round((event.loaded / event.total) * 100));
    };

    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch {
        data = null;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data as Job);
        return;
      }

      reject(new Error(detailMessage(data, `Upload failed (${xhr.status})`)));
    };

    xhr.onerror = () => {
      reject(new Error("Network error while uploading"));
    };

    xhr.send(formData);
  });
}

export function resultDownloadUrl(jobId: string): string {
  return `${API_URL}/jobs/${jobId}/result`;
}
