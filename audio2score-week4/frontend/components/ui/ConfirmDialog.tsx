"use client";

import { useEffect } from "react";

import Button from "./Button";

type ConfirmDialogProps = {
  title: string;
  body: string;
  confirmLabel: string;
  open: boolean;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export default function ConfirmDialog({
  title,
  body,
  confirmLabel,
  open,
  busy = false,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div
      className="ns-dialog-backdrop"
      role="presentation"
      onClick={busy ? undefined : onCancel}
    >
      <div
        className="ns-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="ns-dialog-title"
        aria-describedby="ns-dialog-body"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="ns-dialog-title">{title}</h2>
        <p id="ns-dialog-body">{body}</p>
        <div className="ns-dialog-actions">
          <Button variant="secondary" onClick={onCancel} disabled={busy} autoFocus>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
