import type { MouthState } from "./audio";

export type Light2dLayer = { source: string; rect: [number, number, number, number] };

// ---- 扩展：分层动作支持 ----
export type Light2dHeadLayers = {
  center: Light2dLayer;
  left: Light2dLayer;
  right: Light2dLayer;
  tilt: Light2dLayer;
  eyes_open: Light2dLayer;
};

export type Light2dExtensions = {
  renderer: string;
  idle_actions: string[];
  speak_actions: string[];
  idle_action_period_ms: number;
  keywords: Record<string, string[]>;
  switch_on_sentence_boundary: boolean;
  idle_while_user_speaking: boolean;
};

export type Light2dConfig = {
  version: 1;
  canvas: { width: number; height: number };
  layers: {
    base: Light2dLayer;
    blink: Light2dLayer;
    mouth: Record<MouthState, Light2dLayer>;
    head?: Light2dHeadLayers;
    arms?: Record<string, Light2dLayer>;
  };
  audio: {
    silence_gate: number;
    small_threshold: number;
    medium_threshold: number;
    attack_ms: number;
    release_ms: number;
    crossfade_ms: number;
  };
  animation: {
    breath_period_ms: number;
    breath_scale: number;
    sway_degrees: number;
    blink_period_ms: number;
    blink_duration_ms: number;
  };
  extensions?: Light2dExtensions;
};

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isSource(value: unknown): value is string {
  return typeof value === "string"
    && value.endsWith(".png")
    && !value.startsWith("/")
    && !value.includes("\\")
    && !value.includes(":")
    && !value.includes("?")
    && !value.includes("#")
    && value.split("/").every((part) => Boolean(part) && part !== "." && part !== "..");
}

function isLayer(value: unknown, width: number, height: number): value is Light2dLayer {
  if (!value || typeof value !== "object") return false;
  const layer = value as Partial<Light2dLayer>;
  if (!isSource(layer.source) || !Array.isArray(layer.rect) || layer.rect.length !== 4) return false;
  if (!layer.rect.every(Number.isInteger)) return false;
  const [x, y, rectWidth, rectHeight] = layer.rect;
  return x >= 0 && y >= 0 && rectWidth > 0 && rectHeight > 0
    && x + rectWidth <= width && y + rectHeight <= height;
}

export function parseLight2dConfig(value: unknown): Light2dConfig {
  if (!value || typeof value !== "object") throw new Error("invalid Light2D config");
  const raw = value as Record<string, unknown>;
  const canvas = raw.canvas as Record<string, unknown> | undefined;
  const width = canvas?.width;
  const height = canvas?.height;
  if (raw.version !== 1 || !Number.isInteger(width) || !Number.isInteger(height)) {
    throw new Error("unsupported Light2D config");
  }
  if (!isNumber(width) || !isNumber(height) || width < 1 || width > 4096 || height < 1 || height > 4096) {
    throw new Error("invalid Light2D canvas");
  }
  const layers = raw.layers as Record<string, unknown> | undefined;
  const mouth = layers?.mouth as Record<string, unknown> | undefined;
  const states: MouthState[] = ["closed", "small", "medium", "large"];
  if (!layers || !mouth || !isLayer(layers.base, width, height) || !isLayer(layers.blink, width, height)
    || !states.every((state) => isLayer(mouth[state], width, height))) {
    throw new Error("invalid Light2D layers");
  }
  const audio = raw.audio as Record<string, unknown> | undefined;
  const animation = raw.animation as Record<string, unknown> | undefined;
  if (!audio || !animation) throw new Error("invalid Light2D parameters");
  const audioValues = ["silence_gate", "small_threshold", "medium_threshold", "attack_ms", "release_ms", "crossfade_ms"];
  const animationValues = ["breath_period_ms", "breath_scale", "sway_degrees", "blink_period_ms", "blink_duration_ms"];
  if (!audioValues.every((key) => isNumber(audio[key])) || !animationValues.every((key) => isNumber(animation[key]))) {
    throw new Error("invalid Light2D parameters");
  }
  const gate = audio.silence_gate as number;
  const small = audio.small_threshold as number;
  const medium = audio.medium_threshold as number;
  if (!(0 <= gate && gate < small && small < medium && medium <= 1)) throw new Error("invalid Light2D thresholds");
  if (![audio.attack_ms, audio.release_ms, audio.crossfade_ms].every((item) => (item as number) >= 1 && (item as number) <= 2000)) {
    throw new Error("invalid Light2D timing");
  }
  if ((animation.breath_period_ms as number) <= 0 || (animation.blink_period_ms as number) <= 0
    || (animation.blink_duration_ms as number) <= 0 || (animation.breath_scale as number) < 0
    || (animation.breath_scale as number) > 0.05 || Math.abs(animation.sway_degrees as number) > 5) {
    throw new Error("invalid Light2D animation");
  }

  // ---- 扩展字段（可选）：存在时校验，缺失时保持旧配置可用 ----
  const head = layers.head as Record<string, unknown> | undefined;
  if (head) {
    const headKeys: (keyof Light2dHeadLayers)[] = ["center", "left", "right", "tilt", "eyes_open"];
    if (!headKeys.every((key) => isLayer(head[key], width, height))) {
      throw new Error("invalid Light2D head layers");
    }
  }
  const arms = layers.arms as Record<string, unknown> | undefined;
  if (arms) {
    if (!Object.values(arms).every((layer) => isLayer(layer, width, height))) {
      throw new Error("invalid Light2D arm layers");
    }
  }
  const extensions = raw.extensions as Record<string, unknown> | undefined;
  if (extensions) {
    if (typeof extensions.renderer !== "string"
      || !Array.isArray(extensions.idle_actions) || !extensions.idle_actions.every((a) => typeof a === "string")
      || !Array.isArray(extensions.speak_actions) || !extensions.speak_actions.every((a) => typeof a === "string")
      || !isNumber(extensions.idle_action_period_ms)
      || !extensions.keywords || typeof extensions.keywords !== "object") {
      throw new Error("invalid Light2D extensions");
    }
  }
  return value as Light2dConfig;
}

export function light2dAssetUrl(baseUrl: string, source: string): string {
  const prefix = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  return `${prefix}${source.split("/").map(encodeURIComponent).join("/")}`;
}
