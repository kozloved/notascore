import type { InputHTMLAttributes, ReactNode } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: ReactNode;
  error?: string;
};

export default function Input({
  label,
  hint,
  error,
  id,
  className = "",
  ...props
}: InputProps) {
  const inputId = id || props.name || "field";
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;

  return (
    <label className="ns-field" htmlFor={inputId}>
      <span className="ns-field-label">{label}</span>
      <input
        id={inputId}
        className={`ns-input ${error ? "is-error" : ""} ${className}`.trim()}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        {...props}
      />
      {hint ? (
        <span id={hintId} className="ns-field-hint">
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={errorId} className="ns-field-error" role="alert">
          {error}
        </span>
      ) : null}
    </label>
  );
}
