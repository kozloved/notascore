"use client";

import type { ReactNode } from "react";

export type SegmentOption<T extends string> = {
  value: T;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
  description?: string;
};

type SegmentedControlProps<T extends string> = {
  value: T;
  options: SegmentOption<T>[];
  onChange: (value: T) => void;
  label: string;
  disabled?: boolean;
  compact?: boolean;
};

export default function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  label,
  disabled = false,
  compact = false,
}: SegmentedControlProps<T>) {
  return (
    <div
      className={"ns-segment" + (compact ? " is-compact" : "")}
      role="group"
      aria-label={label}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={
            "ns-segment-option" + (value === option.value ? " is-active" : "")
          }
          onClick={() => onChange(option.value)}
          disabled={disabled || option.disabled}
          aria-pressed={value === option.value}
        >
          {option.icon}
          <span className="ns-segment-copy">
            <span className="ns-segment-label">{option.label}</span>
            {option.description ? (
              <span className="ns-segment-desc">{option.description}</span>
            ) : null}
          </span>
        </button>
      ))}
    </div>
  );
}
