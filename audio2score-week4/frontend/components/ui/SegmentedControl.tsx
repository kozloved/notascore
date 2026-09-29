"use client";

import type { KeyboardEvent, ReactNode } from "react";

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
  const enabledIndexes = options
    .map((option, index) => ({ option, index }))
    .filter(({ option }) => !(disabled || option.disabled));

  const focusSibling = (currentIndex: number, delta: number) => {
    if (!enabledIndexes.length) return;
    const positions = enabledIndexes.map((row) => row.index);
    const at = positions.indexOf(currentIndex);
    const next =
      positions[(at < 0 ? 0 : at + delta + positions.length) % positions.length];
    const button = document.getElementById(
      `ns-segment-${label.replace(/\s+/g, "-")}-${options[next].value}`
    );
    button?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (disabled || options[index]?.disabled) return;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      focusSibling(index, 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      focusSibling(index, -1);
    } else if (event.key === "Home" && enabledIndexes.length) {
      event.preventDefault();
      focusSibling(enabledIndexes[0].index, 0);
    } else if (event.key === "End" && enabledIndexes.length) {
      event.preventDefault();
      focusSibling(enabledIndexes[enabledIndexes.length - 1].index, 0);
    } else if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      onChange(options[index].value);
    }
  };

  return (
    <div
      className={"ns-segment" + (compact ? " is-compact" : "")}
      role="radiogroup"
      aria-label={label}
    >
      {options.map((option, index) => {
        const selected = value === option.value;
        const optionDisabled = disabled || Boolean(option.disabled);
        return (
          <button
            key={option.value}
            id={`ns-segment-${label.replace(/\s+/g, "-")}-${option.value}`}
            type="button"
            role="radio"
            className={
              "ns-segment-option" + (selected ? " is-active" : "")
            }
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            disabled={optionDisabled}
            aria-checked={selected}
            tabIndex={optionDisabled ? -1 : selected ? 0 : -1}
          >
            {option.icon}
            <span className="ns-segment-copy">
              <span className="ns-segment-label">{option.label}</span>
              {option.description ? (
                <span className="ns-segment-desc">{option.description}</span>
              ) : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}
