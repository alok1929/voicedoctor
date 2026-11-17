import { InsetList, InsetRow } from "../../../components/ui/InsetList";
import Slider from "../../../components/ui/Slider";
import PreviewButton from "./PreviewButton";

export type NoisePreset = { id: string; label: string };
export type NoiseType = string;
export type AmbientNoiseConfig = { type: NoiseType; volume: number };

export const NOISE_PREVIEW_SECS = 5;

interface AmbientNoisePickerProps {
  presets: NoisePreset[];
  config: AmbientNoiseConfig;
  previewKey: string;
  previewingKey: string | null;
  onChange: (patch: Partial<AmbientNoiseConfig>) => void;
  onPreview: (id: NoiseType, volume: number, previewKey: string) => void;
}

export default function AmbientNoisePicker({
  presets,
  config,
  previewKey,
  previewingKey,
  onChange,
  onPreview,
}: AmbientNoisePickerProps) {
  return (
    <>
      <InsetList>
        {presets.map(({ id, label }) => {
          const selected = config.type === id;
          const playing = previewingKey === `${previewKey}:${id}`;
          return (
            <InsetRow
              key={id}
              selected={selected}
              onClick={() => onChange({ type: id })}
              trailing={
                <PreviewButton
                  playing={playing}
                  onClick={() => onPreview(id, config.volume, previewKey)}
                  label={`Preview ${NOISE_PREVIEW_SECS}s`}
                />
              }
            >
              <span className="text-body">{label}</span>
            </InsetRow>
          );
        })}
      </InsetList>
      <Slider
        label="Volume"
        value={config.volume}
        display={`${Math.round(config.volume * 100)}%`}
        min={0.1}
        max={1}
        step={0.05}
        onChange={(v) => onChange({ volume: v })}
      />
    </>
  );
}
