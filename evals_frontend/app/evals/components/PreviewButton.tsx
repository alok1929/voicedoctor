import { Play } from "lucide-react";
import Button from "../../../components/ui/Button";
import { ICON_SIZE_SM, ICON_STROKE } from "../../../lib/icons";

interface PreviewButtonProps {
  playing: boolean;
  onClick: () => void;
  label: string;
}

export default function PreviewButton({ playing, onClick, label }: PreviewButtonProps) {
  return (
    <Button
      size="sm"
      variant="secondary"
      className={playing ? "ui-btn--playing" : ""}
      onClick={onClick}
    >
      <Play size={ICON_SIZE_SM} strokeWidth={ICON_STROKE} />
      {playing ? "Playing…" : label}
    </Button>
  );
}
