/**
 * Synthesize and play a subtle notification chime using Web Audio API.
 * No audio file needed — generates a soft two-tone chime programmatically.
 */

let audioContext: AudioContext | null = null;
let audioUnlocked = false;
let gestureUnlockRegistered = false;

function registerGestureUnlock(): void {
  if (gestureUnlockRegistered || typeof window === "undefined") return;
  gestureUnlockRegistered = true;

  const unlock = () => {
    audioUnlocked = true;
    window.removeEventListener("pointerdown", unlock);
    window.removeEventListener("keydown", unlock);
    window.removeEventListener("touchstart", unlock);
  };

  // One real user gesture is enough to satisfy autoplay policy.
  window.addEventListener("pointerdown", unlock, { once: true, passive: true });
  window.addEventListener("keydown", unlock, { once: true, passive: true });
  window.addEventListener("touchstart", unlock, { once: true, passive: true });
}

function getAudioContext(): AudioContext | null {
  registerGestureUnlock();
  if (!audioUnlocked) {
    return null;
  }

  try {
    if (!audioContext || audioContext.state === "closed") {
      audioContext = new AudioContext();
    }
    // Resume if suspended (browser autoplay policy)
    if (audioContext.state === "suspended") {
      void audioContext.resume().catch(() => {});
    }
    return audioContext;
  } catch {
    return null;
  }
}

/**
 * Play a soft two-tone notification chime.
 * First tone: C5 (523 Hz), second tone: E5 (659 Hz) — a pleasant major third.
 */
export function playNotificationSound(): void {
  const ctx = getAudioContext();
  if (!ctx) return;

  const now = ctx.currentTime;
  const volume = 0.12; // Subtle — not jarring

  // Tone 1: C5
  playTone(ctx, 523.25, now, 0.12, volume);
  // Tone 2: E5 (starts slightly after, overlapping)
  playTone(ctx, 659.25, now + 0.1, 0.15, volume * 0.8);
}

function playTone(
  ctx: AudioContext,
  frequency: number,
  startTime: number,
  duration: number,
  volume: number,
): void {
  const oscillator = ctx.createOscillator();
  const gainNode = ctx.createGain();

  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(frequency, startTime);

  // Envelope: quick attack, smooth decay
  gainNode.gain.setValueAtTime(0, startTime);
  gainNode.gain.linearRampToValueAtTime(volume, startTime + 0.01);
  gainNode.gain.exponentialRampToValueAtTime(0.001, startTime + duration);

  oscillator.connect(gainNode);
  gainNode.connect(ctx.destination);

  oscillator.start(startTime);
  oscillator.stop(startTime + duration);
}
