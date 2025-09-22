// frontend/src/components/Settings/hardware/HardwareSection.tsx
import { Section, KV } from "./HardwareUI";
import {
  useSystemResources,
  fmtBytes,
  chooseBestBackend,
} from "./hardwareHooks";
import {
  CpuSection,
  GuardrailsSection,
  GpuSection,
  ResourceMonitorSection,
} from "./HardwareSections";
import { useI18n } from "../../../i18n/i18n";

type Props = {
  effective: Record<string, any> | null;
  overrides: Record<string, any> | null;
  saveOverrides: (obj: Record<string, any>, method?: "patch" | "put") => Promise<any>;
};

export default function HardwareSection({ effective, overrides, saveOverrides }: Props) {
  const h = useSystemResources({ effective, overrides, saveOverrides });
  const { t } = useI18n();

  return (
    <div className="space-y-6">
      {/* System Resources header with copy button */}
      <Section
        title={t("systemResources.title")}
        right={
          <button
            onClick={h.copyResourcesJSON}
            className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
            title={t("systemResources.copyTitle")}
            type="button"
          >
            {h.copied ? t("systemResources.copied") : t("systemResources.copy")}
          </button>
        }
      >
        {/* no body */}
      </Section>

      {/* CPU */}
      <CpuSection snap={h.snap} />

      {/* Memory capacity */}
      <Section title={t("memory.title")} tooltip={t("memory.tooltip")}>
        <div className="text-sm grid grid-cols-2 gap-4">
          <KV label={t("memory.ram")} value={fmtBytes(h.ramTotal)} />
          <KV label={t("memory.vram")} value={fmtBytes(h.gpuTotal)} />
        </div>
      </Section>

      {/* Guardrails */}
      <GuardrailsSection
        curGuardrailsMode={h.curGuardrailsMode}
        setGuardrailsMode={h.setGuardrailsMode}
        curGuardrailsGB={h.curGuardrailsGB}
        setGuardrailsGB={h.setGuardrailsGB}
        curAutoFit={h.curAutoFit}
        setAutoFit={h.setAutoFit}
      />

      {/* GPUs */}
      <GpuSection
        snap={h.snap}
        hasCUDA={h.hasCUDA}
        hasMetal={h.hasMetal}
        hasHip={h.hasHip}
        gpus={h.gpus}
        gpuTotal={h.gpuTotal}
        curBackend={h.curBackend}
        predictedAuto={chooseBestBackend(h.hasCUDA, h.hasMetal, h.hasHip)}
        isDefaultGPUSettings={h.isDefaultGPUSettings}
        resetGPUToDefault={h.resetGPUToDefault}
        curLimitDedicated={h.curLimitDedicated}
        setLimitDedicated={h.setLimitDedicated}
        isEffectivelyCPU={h.isEffectivelyCPU}
        curKV={h.curKV}
        setKV={h.setKV}
        setBackend={h.setBackend}
        gpuChanged={h.gpuChanged}
        gpuBoxRef={h.gpuBoxRef}
      />

      {/* Resource monitor */}
      <ResourceMonitorSection comboUsed={h.comboUsed} cpuPct={h.cpuPct} />
    </div>
  );
}
