"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Home() {
  const [health, setHealth] = useState(null);
  const [file, setFile] = useState(null);
  const [uploadState, setUploadState] = useState("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then(async (response) => {
        if (response.ok) {
          setHealth(await response.json());
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!jobId) return;

    let attempts = 0;
    let timer;

    const poll = async () => {
      attempts += 1;

      try {
        const response = await fetch(`${API_URL}/jobs/${jobId}`);
        const data = await response.json();

        if (response.ok) {
          setJob(data);

          if (data.status === "completed" || data.status === "failed") {
            return;
          }
        }

        if (attempts < 120) {
          timer = setTimeout(poll, 2000);
        }
      } catch (error) {
        if (attempts < 120) {
          timer = setTimeout(poll, 2000);
        }
      }
    };

    timer = setTimeout(poll, 1000);

    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  const handleFileChange = (event) => {
    setFile(event.target.files[0]);
  };

  const handleUpload = async () => {
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    setUploadState("uploading");
    setErrorMessage("");
    setJobId(null);
    setJob(null);

    try {
      const response = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Upload failed");
      }

      setJobId(data.job_id);
      setJob(data);
      setUploadState("success");
    } catch (error) {
      setUploadState("error");
      setErrorMessage(error.message);
    }
  };

  return (
    <main style={{ padding: 40, maxWidth: 860, margin: "0 auto" }}>
      <h1>Audio2Score MVP</h1>
      <p>Upload audio and receive MusicXML.</p>

      <section
        style={{
          marginTop: 24,
          padding: 24,
          border: "1px solid #ddd",
          borderRadius: 10,
          background: "#fff",
        }}
      >
        <h2 style={{ marginTop: 0 }}>Week 4 Transcription Engine</h2>

        {health && (
          <p style={{ color: "#555" }}>
            <strong>API:</strong> {health.status} | <strong>Engine:</strong>{" "}
            {health.engine}
          </p>
        )}

        <div style={{ marginBottom: 16 }}>
          <input
            type="file"
            accept=".wav,.mp3,.m4a,.flac,audio/*"
            onChange={handleFileChange}
            disabled={uploadState === "uploading"}
          />
        </div>

        <button
          onClick={handleUpload}
          disabled={!file || uploadState === "uploading"}
          style={{
            padding: "10px 16px",
            borderRadius: 6,
            border: "1px solid #222",
            background: !file || uploadState === "uploading" ? "#eee" : "#222",
            color: !file || uploadState === "uploading" ? "#666" : "#fff",
            cursor:
              !file || uploadState === "uploading" ? "not-allowed" : "pointer",
          }}
        >
          {uploadState === "uploading" ? "Uploading..." : "Upload Audio"}
        </button>

        {uploadState === "success" && (
          <p style={{ color: "green", marginTop: 16 }}>
            Upload successful. Job queued.
          </p>
        )}

        {uploadState === "error" && (
          <p style={{ color: "red", marginTop: 16 }}>
            Error: {errorMessage}
          </p>
        )}

        {job && (
          <div style={{ marginTop: 24 }}>
            <h3 style={{ marginBottom: 8 }}>Job Status</h3>

            <p>
              <strong>Job ID:</strong> {job.job_id}
            </p>

            <p>
              <strong>Status:</strong> {job.status}
            </p>

            <p>
              <strong>Progress:</strong> {job.progress || 0}%
            </p>

            <div
              style={{
                width: "100%",
                height: 8,
                background: "#eee",
                borderRadius: 6,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${job.progress || 0}%`,
                  height: 8,
                  background: "#222",
                }}
              />
            </div>

            {job.error && (
              <p style={{ color: "red", marginTop: 12 }}>
                Error: {job.error}
              </p>
            )}

            {job.status === "completed" && job.result_available && (
              <div style={{ marginTop: 20 }}>
                <a
                  href={`${API_URL}/jobs/${job.job_id}/result`}
                  download
                  style={{
                    display: "inline-block",
                    padding: "10px 16px",
                    borderRadius: 6,
                    background: "#0a7f2e",
                    color: "#fff",
                    textDecoration: "none",
                  }}
                >
                  Download MusicXML
                </a>

                <p style={{ marginTop: 10, color: "#666" }}>
                  Week 4 output is generated by the configured transcription
                  engine.
                </p>
              </div>
            )}

            <details style={{ marginTop: 20 }}>
              <summary style={{ cursor: "pointer" }}>
                Raw job response
              </summary>

              <pre
                style={{
                  background: "#f7f7f7",
                  padding: 16,
                  borderRadius: 8,
                  overflowX: "auto",
                }}
              >
                {JSON.stringify(job, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </section>
    </main>
  );
}
