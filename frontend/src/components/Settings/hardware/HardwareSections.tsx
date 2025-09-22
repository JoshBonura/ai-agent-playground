// frontend/src/components/Settings/hardware/HardwareSections.tsx
import React from "react";
import { Section, BigStat, ToggleRow } from "./HardwareUI";
import { type Resources } from "../../../api/system";
import { fmtBytes, compatLabel, isCpuCompatible } from "./hardwareHooks";
import { useI18n } from "../../../i18n/i18n";

export function CpuSection({ snap }: { snap: Resources | null }) {
  const { t } = useI18n();

  const status =
    snap?.cpu?.compat?.status ?? (isCpuCompatible(snap?.cpu) ? "compatible" : "unknown");

  const reason =
    snap?.cpu?.compat?.reason ??
    (status === "compatible"
      ? t("cpu.compat.reason.compatible")
      : t("cpu.compat.reason.unknown"));

  // We only take the class from compatLabel; the text comes from i18n
  const { cls: compatCls } = compatLabel(status);
  const compatText =
    status === "compatible"
      ? t("cpu.compat.compatible")
      : status === "incompatible"
      ? t("cpu.compat.incompatible")
      : t("cpu.compat.unknown");

  return (
    <Section
      title={t("cpu.title")}
      tooltip={t("cpu.tooltip")}
      right={
        <span className={`text-xs ${compatCls}`} title={reason}>
          {compatText}
        </span>
      }
    >
      <div className="text-sm space-y-2 w-full">
        {/* Name */}
        <div className="flex items-start gap-3">
          <div className="w-40 shrink-0 text-xs text-gray-500">{t("cpu.name")}</div>
          <div className="font-medium break-words">{snap?.cpu?.name || "—"}</div>
        </div>

        {/* Architecture */}
        <div className="flex items-center gap-3">
          <div className="w-40 shrink-0 text-xs text-gray-500">{t("cpu.arch")}</div>
          <span className="inline-block rounded border px-1.5 py-0.5 text-xs">
            {snap?.cpu?.arch || "—"}
          </span>
          {snap?.osFamily && (
            <span className="ml-2 inline-block rounded border px-1.5 py-0.5 text-[10px]">
              {snap.osFamily}
            </span>
          )}
        </div>

        {/* Instruction Set Extensions */}
        <div className="flex items-start gap-3">
          <div className="w-40 shrink-0 text-xs text-gray-500">{t("cpu.isa")}</div>
          <div className="flex flex-wrap gap-2">
            {(snap?.cpu?.isa ?? []).length > 0 ? (
              (snap?.cpu?.isa ?? []).map((b) => (
                <span key={b} className="inline-block rounded border px-1.5 py-0.5 text-[10px]">
                  {b}
                </span>
              ))
            ) : (
              <span className="text-xs text-gray-400">—</span>
            )}
          </div>
        </div>
      </div>
    </Section>
  );
}

export function GuardrailsSection({
  curGuardrailsMode,
  setGuardrailsMode,
  curGuardrailsGB,
  setGuardrailsGB,
  curAutoFit,
  setAutoFit,
}: {
  curGuardrailsMode: string;
  setGuardrailsMode: (v: string) => Promise<void>;
  curGuardrailsGB: number;
  setGuardrailsGB: (v: number) => Promise<void>;
  curAutoFit: boolean;
  setAutoFit: (b: boolean) => Promise<void>;
}) {
  const { t } = useI18n();

  return (
    <Section title={t("guardrails.title")} tooltip={t("guardrails.tooltip")}>
      <div className="text-xs text-gray-600 mb-2">{t("guardrails.header")}</div>

      <div className="flex items-center gap-3">
        <select
          className="border rounded px-2 py-1 text-sm"
          value={curGuardrailsMode}
          onChange={(e) => void setGuardrailsMode(e.target.value)}
        >
          <option value="off">{t("guardrails.mode.off")}</option>
          <option value="relaxed">{t("guardrails.mode.relaxed")}</option>
          <option value="balanced">{t("guardrails.mode.balanced")}</option>
          <option value="strict">{t("guardrails.mode.strict")}</option>
          <option value="custom">{t("guardrails.mode.custom")}</option>
        </select>

        {curGuardrailsMode === "custom" && (
          <div className="flex items-center gap-2">
            <span className="text-sm">{t("guardrails.custom.label")}</span>
            <input
              type="number"
              min={1}
              step={1}
              className="w-20 border rounded px-2 py-1 text-sm"
              value={curGuardrailsGB}
              onChange={(e) => void setGuardrailsGB(parseInt(e.target.value || "0", 10))}
            />
            <span className="text-sm">{t("guardrails.custom.suffixGB")}</span>
          </div>
        )}
      </div>

      <div className="mt-3 space-y-3">
        <ToggleRow
          title={t("guardrails.autofit.title")}
          subtitle={t("guardrails.autofit.subtitle")}
          checked={!!curAutoFit}
          onChange={(b) => void setAutoFit(b)}
        />
      </div>
    </Section>
  );
}

export function GpuSection({
  hasCUDA,
  hasMetal,
  hasHip,
  gpus,
  gpuTotal,
  curBackend,
  predictedAuto,
  isDefaultGPUSettings,
  resetGPUToDefault,
  curLimitDedicated,
  setLimitDedicated,
  isEffectivelyCPU,
  curKV,
  setKV,
  setBackend,
  gpuChanged,
  gpuBoxRef,
}: {
  snap: Resources | null;
  hasCUDA: boolean;
  hasMetal: boolean;
  hasHip: boolean;
  gpus: NonNullable<Resources["gpus"]>;
  gpuTotal: number;
  curBackend: string;
  predictedAuto: string;
  isDefaultGPUSettings: boolean;
  resetGPUToDefault: () => Promise<void>;
  curLimitDedicated: boolean;
  setLimitDedicated: (b: boolean) => Promise<void>;
  isEffectivelyCPU: boolean;
  curKV: boolean;
  setKV: (b: boolean) => Promise<void>;
  setBackend: (v: string) => Promise<void>;
  gpuChanged: boolean;
  gpuBoxRef: React.RefObject<HTMLDivElement | null>;
}) {
  const { t } = useI18n();

  const count = gpus.length || 0;
  const plural = count === 1 ? "" : "s";
  const detected = hasCUDA
    ? t("gpu.detected.withCuda", { count, plural })
    : t("gpu.detected.noCuda", { count, plural });

  return (
    <Section title={t("gpu.title")} tooltip={t("gpu.tooltip")}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-gray-600">{detected}</div>
        <button
          type="button"
          onClick={resetGPUToDefault}
          disabled={isDefaultGPUSettings}
          className={`text-xs px-3 py-1.5 rounded border ${
            isDefaultGPUSettings ? "opacity-50 cursor-not-allowed" : "hover:bg-gray-50"
          }`}
          title={
            isDefaultGPUSettings
              ? t("gpu.reset.title.disabled")
              : t("gpu.reset.title.enabled")
          }
        >
          {t("gpu.reset")}
        </button>
      </div>

      <div className="space-y-3">
        <ToggleRow
          title={t("gpu.limitDedicated.title")}
          subtitle={t("gpu.limitDedicated.subtitle")}
          checked={!!curLimitDedicated}
          disabled={!hasCUDA}
          onChange={(b) => void setLimitDedicated(b)}
        />

        <div
          ref={gpuBoxRef as React.RefObject<HTMLDivElement>}
          className={`rounded-lg border ${!hasCUDA && !hasMetal && !hasHip ? "opacity-60" : ""}`}
          style={{ contain: "layout paint" }}
        >
          <div className="p-3 flex items-center justify-between">
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">
                {gpus[0]?.name ||
                  (hasMetal ? t("gpu.card.apple") : hasHip ? t("gpu.card.amd") : t("gpu.card.none"))}
              </div>
              <div className="text-xs text-gray-600">
                {t("gpu.card.vramCapacity")} {fmtBytes(gpuTotal)}{" "}
                {(hasCUDA || hasMetal || hasHip) && (
                  <span className="ml-2 inline-block text-[10px] px-1.5 py-0.5 rounded border">
                    {hasCUDA
                      ? t("gpu.card.accel.cuda")
                      : hasMetal
                      ? t("gpu.card.accel.metal")
                      : t("gpu.card.accel.hip")}
                  </span>
                )}
                {curBackend === "auto" && (
                  <span className="ml-2 text[11px] text-gray-500">
                    {t("gpu.card.autoWouldPick", {
                      backend: predictedAuto.toUpperCase(),
                    })}
                  </span>
                )}
              </div>
            </div>
            <select
              className="border rounded px-2 py-1 text-sm"
              value={curBackend}
              onChange={(e) => void setBackend(e.target.value)}
            >
              <option value="auto">{t("gpu.backend.auto")}</option>
              <option value="cpu">{t("gpu.backend.cpu")}</option>
              <option value="cuda" disabled={!hasCUDA}>
                {t("gpu.backend.cuda")}
              </option>
              <option value="metal" disabled={!hasMetal}>
                {t("gpu.backend.metal")}
              </option>
              <option value="hip" disabled={!hasHip}>
                {t("gpu.backend.hip")}
              </option>
            </select>
          </div>
        </div>

        <ToggleRow
          title={t("gpu.kv.title")}
          subtitle={isEffectivelyCPU ? t("gpu.kv.subtitle.cpu") : t("gpu.kv.subtitle.gpu")}
          checked={!!curKV}
          disabled={isEffectivelyCPU}
          onChange={(b) => void setKV(b)}
        />

        {gpuChanged && (
          <div className="mt-3 flex items-start gap-2 text-xs text-gray-500">
            <span className="mt-[2px] inline-block w-4 h-4 rounded-full border text-[10px] text-gray-500 text-center select-none">
              i
            </span>
            <div>{t("gpu.note.changesApply")}</div>
          </div>
        )}
      </div>
    </Section>
  );
}

export function ResourceMonitorSection({
  comboUsed,
  cpuPct,
}: {
  comboUsed: number;
  cpuPct: number | null;
}) {
  const { t } = useI18n();

  return (
    <Section title={t("monitor.title")} tooltip={t("monitor.tooltip")}>
      <div className="text-xs text-gray-600 mb-2">{t("monitor.disclaimer")}</div>
      <div className="grid grid-cols-2 gap-4">
        <BigStat title={t("monitor.ramvram")} value={fmtBytes(comboUsed)} />
        <BigStat title={t("monitor.cpu")} value={cpuPct == null ? "—" : `${cpuPct.toFixed(2)}%`} />
      </div>
    </Section>
  );
}
