import { Globe, MessageSquare, Radio, Volume2 } from "lucide-react";

export type SimType = "baseline" | "ambient_noise" | "barge_in" | "language_switch";

export type SimCounts = Record<SimType, number>;

export const SIM_ORDER: SimType[] = ["baseline", "ambient_noise", "barge_in", "language_switch"];

export const SIM_META: Record<
  SimType,
  { Icon: React.ElementType; label: string; desc: string }
> = {
  baseline: { Icon: Radio, label: "Baseline", desc: "Clean call, no simulation" },
  ambient_noise: { Icon: Volume2, label: "Ambient noise", desc: "Background noise presets with preview" },
  barge_in: { Icon: MessageSquare, label: "Barge-in", desc: "Tester interrupts mid-turn" },
  language_switch: { Icon: Globe, label: "Language switch", desc: "Tester switches language mid-call" },
};
