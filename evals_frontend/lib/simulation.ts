/** Human labels for the simulation kinds a call can run with. */
export const SIMULATION_LABELS: Record<string, string> = {
  ambient_noise: "Ambient noise",
  barge_in: "Barge-in",
  language_switch: "Language switch",
};

/** Scenario descriptions for the built-in sound presets — what the agent actually
 * heard on the line. Shown as "Preset / real-world scenario". */
const SOUND_SCENARIOS: Record<string, string> = {
  cafe: "Café / busy coffee-shop chatter",
  factory: "Factory / machinery running nearby",
  animal: "Animal / farm animals calling nearby",
  tractor: "Tractor / diesel engine idling nearby",
  trucks: "Trucks / heavy vehicles passing by",
  trucksounds: "Trucks / heavy vehicles passing by",
  farm: "Farm / livestock and machinery nearby",
  construction: "Construction / drilling and site noise",
  dogbarking: "Dog / barking close to the caller",
};

export function simulationLabel(kind: string): string {
  return SIMULATION_LABELS[kind] || kind.replace(/_/g, " ");
}

export function simulationKindsLabel(kinds: string[] | undefined | null): string | null {
  if (!kinds || kinds.length === 0) return null;
  return kinds.map(simulationLabel).join(" + ");
}

export function soundScenario(id: string | null | undefined): string | null {
  if (!id) return null;
  const key = String(id).toLowerCase();
  if (SOUND_SCENARIOS[key]) return SOUND_SCENARIOS[key];
  if (key.startsWith("lib_")) return "Custom uploaded sound";
  return key.replace(/_/g, " ");
}

interface SimBlock {
  enabled?: boolean;
  type?: string;
  style?: string;
  sound_type?: string;
}

/** Derive which simulations ran and the sound used from a full report meta.
 * Mirrors `simulation_summary` in the backend's reports route. */
export function simulationSummary(meta: {
  simulations?: Record<string, unknown>;
  background_noise?: string;
  test_interruptions?: boolean;
}): { kinds: string[]; sound: string | null } {
  const sims = (meta.simulations || {}) as Record<string, SimBlock | undefined>;
  const kinds: string[] = [];
  let sound: string | null = null;

  const noise = sims.ambient_noise;
  if (noise?.enabled) {
    kinds.push("ambient_noise");
    sound = noise.type || null;
  }
  const barge = sims.barge_in;
  if (barge?.enabled) {
    kinds.push("barge_in");
    if (!sound && (barge.style === "sound" || barge.style === "both")) {
      sound = barge.sound_type || null;
    }
  }
  if (sims.language_switch?.enabled) kinds.push("language_switch");

  if (kinds.length === 0) {
    const bg = (meta.background_noise || "").toLowerCase();
    if (bg && bg !== "off") {
      kinds.push("ambient_noise");
      sound = bg;
    }
    if (meta.test_interruptions) kinds.push("barge_in");
  }
  return { kinds, sound };
}
