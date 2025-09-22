// frontend/src/components/Settings/hardware/HardwareUI.tsx
import React from "react";

export function Section({
  title,
  children,
  tooltip,
  right,
}: {
  title: string | React.ReactNode;
  children?: React.ReactNode; // optional
  tooltip?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border p-4 relative">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold">
          <span className="min-w-0 truncate">{title}</span>
          {tooltip && (
            <span
              className="inline-flex items-center justify-center w-4 h-4 rounded-full border text-[10px] text-gray-500 cursor-help"
              title={tooltip}
              aria-label={tooltip}
              role="img"
            >
              ?
            </span>
          )}
        </div>
        {right ? <div className="shrink-0">{right}</div> : null}
      </div>
      {children}
    </div>
  );
}

export function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg border px-3 py-2">
      <div className="text-xs text-gray-600">{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

export function BigStat({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-xl border px-4 py-6 text-center">
      <div className="text-xs text-gray-600 mb-2">{title}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

export function ToggleRow({
  title,
  subtitle,
  checked,
  disabled,
  onChange,
}: {
  title: string;
  subtitle?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (b: boolean) => void;
}) {
  return (
    <div className={`rounded-lg border ${disabled ? "opacity-60" : ""}`}>
      <div className="p-3 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="text-sm font-medium">{title}</div>
          {subtitle && <div className="text-xs text-gray-600">{subtitle}</div>}
        </div>
        <label className="inline-flex items-center cursor-pointer select-none">
          <input
            type="checkbox"
            className="sr-only"
            checked={!!checked}
            disabled={disabled}
            onChange={(e) => onChange(e.target.checked)}
            aria-checked={!!checked}
            aria-disabled={!!disabled}
          />
          <span
            aria-hidden="true"
            className={`w-10 h-5 rounded-full border transition-colors ${
              checked ? "bg-black" : "bg-gray-200"
            }`}
          />
        </label>
      </div>
    </div>
  );
}
