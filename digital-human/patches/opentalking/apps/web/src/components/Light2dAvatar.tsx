import { useEffect, useRef } from "react";

import { buildApiUrl } from "../lib/api";
import type { ClientRendererDescriptor } from "../lib/api";
import { computeRms, createEnergySmoother, mouthStateForEnergy, type MouthState } from "../light2d/audio";
import { actionForAnswer, pickRandom } from "../light2d/actions";
import { light2dAssetUrl, parseLight2dConfig, type Light2dConfig, type Light2dLayer } from "../light2d/config";

type Light2dAvatarProps = {
  renderer: ClientRendererDescriptor;
  stream: MediaStream | null;
  /** 数字人回答的文本（字幕），用于关键词触发动作 */
  subtitle?: string | null;
  className?: string;
  onRendererError: () => void;
};

type LayerImages = {
  base: HTMLImageElement;
  blink: HTMLImageElement;
  mouth: Record<MouthState, HTMLImageElement>;
  head?: {
    center: HTMLImageElement;
    left: HTMLImageElement;
    right: HTMLImageElement;
    tilt: HTMLImageElement;
    eyes_open: HTMLImageElement;
  };
  arms?: Record<string, HTMLImageElement>;
};

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Light2D asset failed: ${url}`));
    image.src = url;
  });
}

async function loadImages(config: Light2dConfig, assetBaseUrl: string): Promise<LayerImages> {
  const load = (layer: Light2dLayer) => loadImage(light2dAssetUrl(buildApiUrl(assetBaseUrl), layer.source));
  const [base, blink, closed, small, medium, large] = await Promise.all([
    load(config.layers.base),
    load(config.layers.blink),
    load(config.layers.mouth.closed),
    load(config.layers.mouth.small),
    load(config.layers.mouth.medium),
    load(config.layers.mouth.large),
  ]);
  const result: LayerImages = { base, blink, mouth: { closed, small, medium, large } };

  // 扩展：头部变体
  const head = config.layers.head;
  if (head) {
    const [center, left, right, tilt, eyesOpen] = await Promise.all([
      load(head.center), load(head.left), load(head.right), load(head.tilt), load(head.eyes_open),
    ]);
    result.head = { center, left, right, tilt, eyes_open: eyesOpen };
  }

  // 扩展：手臂姿势
  const arms = config.layers.arms;
  if (arms) {
    const entries = await Promise.all(
      Object.entries(arms).map(async ([name, layer]) => [name, await load(layer)] as const),
    );
    result.arms = Object.fromEntries(entries);
  }

  return result;
}

function drawLayer(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  layer: Light2dLayer,
  alpha = 1,
): void {
  const [x, y, width, height] = layer.rect;
  context.globalAlpha = alpha;
  context.drawImage(image, x, y, width, height);
  context.globalAlpha = 1;
}

export function Light2dAvatar({ renderer, stream, subtitle = null, className = "", onRendererError }: Light2dAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const subtitleRef = useRef<string | null>(subtitle);
  subtitleRef.current = subtitle;

  useEffect(() => {
    let cancelled = false;
    let animationFrame = 0;
    let audioContext: AudioContext | null = null;
    let sourceNode: MediaStreamAudioSourceNode | null = null;
    let analyser: AnalyserNode | null = null;
    let resumeAudio = () => undefined;

    const start = async () => {
      const response = await fetch(buildApiUrl(renderer.config_url), { cache: "no-store" });
      if (!response.ok) throw new Error(`Light2D config failed: ${response.status}`);
      const config = parseLight2dConfig(await response.json());
      const images = await loadImages(config, renderer.asset_base_url);
      if (cancelled) return;

      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) throw new Error("Canvas 2D is unavailable");
      canvas.width = config.canvas.width;
      canvas.height = config.canvas.height;

      const audioTracks = stream?.getAudioTracks() ?? [];
      if (stream && audioTracks.length > 0) {
        audioContext = new AudioContext();
        resumeAudio = () => {
          if (audioContext?.state === "suspended") void audioContext.resume().catch(() => undefined);
        };
        window.addEventListener("pointerdown", resumeAudio, { passive: true });
        window.addEventListener("keydown", resumeAudio);
        resumeAudio();
        sourceNode = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0;
        sourceNode.connect(analyser);
      }

      const ext = config.extensions;
      const idleActions = ext?.idle_actions ?? [];
      const speakActions = ext?.speak_actions ?? [];
      const keywords = ext?.keywords ?? {};
      const idlePeriod = ext?.idle_action_period_ms ?? 5000;
      const switchOnBoundary = ext?.switch_on_sentence_boundary ?? false;
      // idle_while_user_speaking: 用户说话时（无音频能量）走待机轮播，此处恒为待机，保留字段供配置读取
      void ext?.idle_while_user_speaking;

      const samples = new Float32Array(analyser?.fftSize ?? 1024);
      const smoother = createEnergySmoother(config.audio);
      let currentMouth: MouthState = "closed";
      let previousMouth: MouthState = "closed";
      let mouthChangedAt = performance.now();
      let lastTime = performance.now();

      // 动作状态
      let currentAction = "";
      let lastSpokenText = "";
      let lastIdleSwitch = 0;
      let speaking = false;

      const setActionFromText = (text: string) => {
        if (!ext || !images.arms) return;
        if (!text.trim()) return;
        // 按分句边界触发：取最后命中关键词的动作
        const matched = actionForAnswer(text, keywords, switchOnBoundary);
        const fallback = pickRandom(speakActions, currentAction);
        currentAction = matched && images.arms[matched] ? matched : fallback;
      };

      const render = (now: number) => {
        if (cancelled) return;
        const deltaMs = Math.min(100, Math.max(0, now - lastTime));
        lastTime = now;
        let rawEnergy = 0;
        if (analyser) {
          analyser.getFloatTimeDomainData(samples);
          rawEnergy = computeRms(samples);
        }
        const gatedEnergy = rawEnergy < config.audio.silence_gate ? 0 : rawEnergy;
        const energy = smoother.update(gatedEnergy, deltaMs);
        const nextMouth = mouthStateForEnergy(energy, config.audio);
        if (nextMouth !== currentMouth) {
          previousMouth = currentMouth;
          currentMouth = nextMouth;
          mouthChangedAt = now;
        }
        const mouthProgress = Math.min(1, (now - mouthChangedAt) / config.audio.crossfade_ms);
        const breathPhase = (now % config.animation.breath_period_ms) / config.animation.breath_period_ms;
        const swayPhase = breathPhase * Math.PI * 2;
        const speakingWeight = Math.min(1, energy / Math.max(config.audio.medium_threshold, 0.001));
        const scaleY = 1 + Math.sin(swayPhase) * config.animation.breath_scale + speakingWeight * 0.003;
        const rotation = Math.sin(swayPhase * 0.75) * config.animation.sway_degrees + speakingWeight * 0.12;
        const blinkLocal = now % config.animation.blink_period_ms;
        const blinking = blinkLocal < config.animation.blink_duration_ms;

        // 数字人在说话（有音频能量）
        const isSpeaking = energy >= config.audio.silence_gate;
        const text = subtitleRef.current ?? "";

        if (ext && images.arms) {
          if (isSpeaking) {
            // 说话时：讲解动作；回答文本变化时按关键词/分句切换
            if (!speaking || text !== lastSpokenText) {
              setActionFromText(text);
              lastSpokenText = text;
              speaking = true;
            }
          } else {
            // 不说话时（含听用户说话）：待机动作随机轮播
            if (speaking || now - lastIdleSwitch >= idlePeriod) {
              currentAction = pickRandom(idleActions, currentAction);
              lastIdleSwitch = now;
              speaking = false;
            }
          }
        }

        context.clearRect(0, 0, canvas.width, canvas.height);
        context.save();
        context.translate(canvas.width / 2, canvas.height);
        context.rotate((rotation * Math.PI) / 180);
        context.scale(1, scaleY);
        context.translate(-canvas.width / 2, -canvas.height);

        // 底图（身体）
        drawLayer(context, images.base, config.layers.base);

        // 扩展：头部变体，随动作切换（指引→侧转，思考→歪头，其余→正面）
        if (images.head) {
          const head = config.layers.head!;
          let headImg = images.head.center;
          let headLayer = head.center;
          if (currentAction === "speak_think") {
            headImg = images.head.tilt; headLayer = head.tilt;
          } else if (currentAction === "idle_look_left" || currentAction === "speak_point") {
            headImg = images.head.left; headLayer = head.left;
          } else if (currentAction === "idle_look_right") {
            headImg = images.head.right; headLayer = head.right;
          }
          drawLayer(context, headImg, headLayer);
          // 头图本身没有眼睛：睁眼画 eyes_open，眨眼画 blink(eyes_blink) 覆盖
          if (!blinking) {
            drawLayer(context, images.head.eyes_open, head.eyes_open);
          } else {
            drawLayer(context, images.blink, config.layers.blink);
          }
        }

        // 扩展：手臂动作图层
        if (images.arms && currentAction && images.arms[currentAction] && config.layers.arms) {
          drawLayer(context, images.arms[currentAction], config.layers.arms[currentAction]);
        }

        // 嘴型（能量驱动，卡通 4 档）
        if (mouthProgress < 1 && previousMouth !== currentMouth) {
          drawLayer(context, images.mouth[previousMouth], config.layers.mouth[previousMouth], 1 - mouthProgress);
        }
        drawLayer(context, images.mouth[currentMouth], config.layers.mouth[currentMouth], mouthProgress);

        // 眨眼（旧配置：独立 eyes-closed 图）
        if (!images.head && blinking) drawLayer(context, images.blink, config.layers.blink);

        context.restore();
        context.globalAlpha = 1;
        canvas.dataset.mouthState = currentMouth;
        canvas.dataset.audioEnergy = energy.toFixed(4);
        canvas.dataset.action = currentAction;
        canvas.dataset.rendererReady = "true";
        animationFrame = requestAnimationFrame(render);
      };
      animationFrame = requestAnimationFrame(render);
    };

    void start().catch((error) => {
      if (!cancelled) {
        console.warn("Light2D renderer failed", error);
        onRendererError();
      }
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(animationFrame);
      window.removeEventListener("pointerdown", resumeAudio);
      window.removeEventListener("keydown", resumeAudio);
      sourceNode?.disconnect();
      analyser?.disconnect();
      if (audioContext) void audioContext.close();
    };
  }, [onRendererError, renderer.asset_base_url, renderer.config_url, stream]);

  return <canvas ref={canvasRef} className={`h-full w-full object-contain ${className}`} aria-label="Light2D 动漫形象" />;
}
