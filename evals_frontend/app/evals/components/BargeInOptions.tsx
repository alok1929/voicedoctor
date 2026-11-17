import SegmentedControl from "../../../components/ui/SegmentedControl";
import Slider from "../../../components/ui/Slider";
import Switch from "../../../components/ui/Switch";
import { InsetList, InsetRow } from "../../../components/ui/InsetList";
import InterruptionSoundPicker, { type InterruptionPreset } from "./InterruptionSoundPicker";
import PreviewButton from "./PreviewButton";

export type FillerPreset = { id: string; label: string };

export type BargeInConfig = {
  real_count: number;
  after_secs: number;
  style: "speech" | "sound" | "both" | "speech_probes";
  sound_type: string;
  sound_volume: number;
  fake_count: number;
  fake_burst_secs: number;
  fake_volume: number;
  cough_enabled: boolean;
  hmm_enabled: boolean;
  filler_volume: number;
  probe_stop_enabled: boolean;
  probe_start_enabled: boolean;
  enabled_custom_reactions: string[];
};

const STYLE_OPTIONS = [
  { value: "speech" as const, label: "Speech" },
  { value: "sound" as const, label: "Sound" },
  { value: "both" as const, label: "Both" },
  { value: "speech_probes" as const, label: "Speech probes" },
];

const BUILTIN_FILLERS = ["cough", "hmm"] as const;

interface BargeInOptionsProps {
  config: BargeInConfig;
  presets: InterruptionPreset[];
  customReactions: FillerPreset[];
  previewKey: string;
  previewingKey: string | null;
  onChange: (patch: Partial<BargeInConfig>) => void;
  onPreviewInterruption: (id: string, previewKey: string, volume: number) => void;
  onPreviewFiller: (id: string, previewKey: string, volume: number) => void;
}

export default function BargeInOptions({
  config,
  presets,
  customReactions,
  previewKey,
  previewingKey,
  onChange,
  onPreviewInterruption,
  onPreviewFiller,
}: BargeInOptionsProps) {
  const needsSound = config.style === "sound" || config.style === "both";
  const isSpeechProbes = config.style === "speech_probes";
  const customOnly = customReactions.filter((p) => !BUILTIN_FILLERS.includes(p.id as typeof BUILTIN_FILLERS[number]));

  function toggleCustomReaction(id: string, enabled: boolean) {
    const current = config.enabled_custom_reactions || [];
    const next = enabled
      ? [...new Set([...current, id])]
      : current.filter((x) => x !== id);
    onChange({ enabled_custom_reactions: next });
  }

  return (
    <>
      <p className="text-label">Barge-in style</p>
      <SegmentedControl
        options={STYLE_OPTIONS}
        value={config.style}
        onChange={(s) => onChange({ style: s })}
      />

      {isSpeechProbes && (
        <>
          <p className="text-caption" style={{ margin: "var(--space-3) 0" }}>
            Scripted flow: greeting → objective → optional &quot;stop stop&quot; / &quot;start start&quot; → hmm/ho/ha fillers → cough sound.
            Measures command response latency and false stops on non-commands.
          </p>
          <p className="text-label">Speech probe commands</p>
          <InsetList>
            <Switch
              checked={config.probe_stop_enabled}
              onChange={(v) => onChange({ probe_stop_enabled: v })}
              label='Say "stop stop"'
            />
            <Switch
              checked={config.probe_start_enabled}
              onChange={(v) => onChange({ probe_start_enabled: v })}
              label='Say "start start"'
            />
          </InsetList>
        </>
      )}

      {needsSound && (
        <>
          <p className="text-label" style={{ marginTop: "var(--space-4)" }}>Interruption sound</p>
          <InterruptionSoundPicker
            presets={presets}
            soundType={config.sound_type}
            previewKey={previewKey}
            previewingKey={previewingKey}
            onChange={(sound_type) => onChange({ sound_type })}
            onPreview={(id) => onPreviewInterruption(id, previewKey, config.sound_volume)}
          />
          <Slider
            label="Sound volume"
            value={config.sound_volume}
            display={`${Math.round(config.sound_volume * 100)}%`}
            min={0.1}
            max={1}
            step={0.05}
            onChange={(v) => onChange({ sound_volume: v })}
          />
        </>
      )}

      {isSpeechProbes && (
        <Slider
          label="Cough volume"
          value={config.sound_volume}
          display={`${Math.round(config.sound_volume * 100)}%`}
          min={0.1}
          max={1}
          step={0.05}
          onChange={(v) => onChange({ sound_volume: v })}
        />
      )}

      {!isSpeechProbes && (
        <>
          <Slider
            label="Barge-ins per call"
            value={config.real_count}
            display={`${config.real_count}`}
            min={1}
            max={5}
            step={1}
            onChange={(v) => onChange({ real_count: v })}
          />
          <Slider
            label="First barge-in after"
            value={config.after_secs}
            display={`${config.after_secs}s`}
            min={0.1}
            max={10}
            step={0.1}
            onChange={(v) => onChange({ after_secs: v })}
          />
        </>
      )}

      {isSpeechProbes && (
        <Slider
          label="Probe inject after"
          value={config.after_secs}
          display={`${config.after_secs}s`}
          min={0.1}
          max={10}
          step={0.1}
          onChange={(v) => onChange({ after_secs: v })}
        />
      )}

      <div style={{ marginTop: "var(--space-4)", paddingTop: "var(--space-4)", borderTop: "1px solid var(--separator)" }}>
        <p className="text-label">Caller reactions (while agent speaks)</p>
        <p className="text-caption" style={{ marginBottom: "var(--space-3)" }}>
          Play cough or hmm on your side whenever the agent is talking — every response, not just the first.
        </p>
        <InsetList>
          {(["cough", "hmm"] as const).map((kind) => {
            const enabled = kind === "cough" ? config.cough_enabled : config.hmm_enabled;
            const playing = previewingKey === `filler:${previewKey}:${kind}`;
            const label = kind === "cough" ? "Cough" : "Hmm";
            return (
              <InsetRow
                key={kind}
                trailing={
                  <PreviewButton
                    playing={playing}
                    onClick={() => onPreviewFiller(kind, previewKey, config.filler_volume)}
                    label="Preview"
                  />
                }
              >
                <Switch
                  checked={enabled}
                  onChange={(v) =>
                    onChange(kind === "cough" ? { cough_enabled: v } : { hmm_enabled: v })
                  }
                  label={label}
                />
              </InsetRow>
            );
          })}
          {customOnly.map(({ id, label }) => {
            const enabled = (config.enabled_custom_reactions || []).includes(id);
            const playing = previewingKey === `filler:${previewKey}:${id}`;
            return (
              <InsetRow
                key={id}
                trailing={
                  <PreviewButton
                    playing={playing}
                    onClick={() => onPreviewFiller(id, previewKey, config.filler_volume)}
                    label="Preview"
                  />
                }
              >
                <Switch
                  checked={enabled}
                  onChange={(v) => toggleCustomReaction(id, v)}
                  label={label}
                />
              </InsetRow>
            );
          })}
        </InsetList>
        <Slider
          label="Reaction volume"
          value={config.filler_volume}
          display={`${Math.round(config.filler_volume * 100)}%`}
          min={0.1}
          max={1}
          step={0.05}
          onChange={(v) => onChange({ filler_volume: v })}
        />
      </div>
    </>
  );
}
