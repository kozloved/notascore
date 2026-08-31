"use client";

import { useEffect, useState } from "react";

import { track } from "../../lib/analytics";
import { renameScore } from "../../lib/jobs";

export default function EditableTitle({
  id,
  title,
  onSaved,
}: {
  id: string;
  title: string;
  onSaved?: (title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(title);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setValue(title);
  }, [title]);

  const save = async () => {
    const next = value.trim() || title;
    setEditing(false);
    if (next === title) {
      setValue(title);
      return;
    }
    try {
      const updated = await renameScore(id, next);
      const saved = updated.title || next;
      setValue(saved);
      onSaved?.(saved);
      track("score_renamed");
      setMessage("Score renamed");
      window.setTimeout(() => setMessage(""), 2500);
    } catch {
      setValue(title);
      setMessage("We couldn’t rename this score.");
    }
  };

  if (!editing) {
    return (
      <div className="ns-title-edit">
        <button
          type="button"
          className="ns-title-button"
          onClick={() => setEditing(true)}
        >
          {title}
        </button>
        {message ? (
          <span className="ns-title-feedback" role="status">
            {message}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div className="ns-title-edit">
      <label className="sr-only" htmlFor={`score-title-${id}`}>
        Score title
      </label>
      <input
        id={`score-title-${id}`}
        className="ns-input ns-title-input"
        value={value}
        autoFocus
        onChange={(event) => setValue(event.target.value)}
        onBlur={() => void save()}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void save();
          }
          if (event.key === "Escape") {
            setValue(title);
            setEditing(false);
          }
        }}
      />
    </div>
  );
}
