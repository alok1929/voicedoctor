import { InsetList, InsetRow } from "../../../components/ui/InsetList";
import PreviewButton from "./PreviewButton";
import { INTERRUPTION_PREVIEW_SECS } from "./constants";

export type InterruptionPreset = { id: string; label: string };

interface InterruptionSoundPickerProps {
  presets: InterruptionPreset[];
  soundType: string;
  previewKey: string;
  previewingKey: string | null;
  onChange: (sound_type: string) => void;
  onPreview: (id: string) => void;
}

export default function InterruptionSoundPicker({
  presets,
  soundType,
  previewKey,
  previewingKey,
  onChange,
  onPreview,
}: InterruptionSoundPickerProps) {
  return (
    <InsetList>
      {presets.map(({ id, label }) => {
        const selected = soundType === id;
        const playing = previewingKey === `int:${previewKey}:${id}`;
        return (
          <InsetRow
            key={id}
            selected={selected}
            onClick={() => onChange(id)}
            trailing={
              <PreviewButton
                playing={playing}
                onClick={() => onPreview(id)}
                label={`Preview ${INTERRUPTION_PREVIEW_SECS}s`}
              />
            }
          >
            <span className="text-body">{label}</span>
          </InsetRow>
        );
      })}
    </InsetList>
  );
}
