/**
 * The auth background "film": a slow camera drift over a perspective grid with
 * an endless candlestick chart floating above the horizon, a glowing price
 * line, drifting dust and a soft purple light. Pure Canvas 2D — no libraries,
 * no media files. Monochrome (white/gray on near-black) with one purple glow.
 *
 * `drawScene(ctx, w, h, t)` is deterministic for a given `t` (seconds), so the
 * same function renders both the animation and the reduced-motion still.
 */

const PURPLE = "158, 79, 224"; // #9E4FE0
const LAVENDER = "200, 162, 240"; // #C8A2F0

/** Seconds into the film used for the static (reduced-motion) frame. */
export const STILL_FRAME_T = 42;

function hash(n: number): number {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

/** A smooth, endless, bounded "price" series (no trend: nothing here implies profit). */
function price(i: number): number {
  return 1.0 * Math.sin(i * 0.045) + 0.5 * Math.sin(i * 0.13 + 1.3) + 0.26 * Math.sin(i * 0.31 + 0.4) + 0.32 * (hash(i) - 0.5);
}

type Dust = { x: number; y: number; z: number; s: number };
const DUST: Dust[] = Array.from({ length: 70 }, (_, i) => ({ x: (hash(i + 0.1) - 0.5) * 30, y: 0.2 + hash(i + 0.2) * 6, z: 2 + hash(i + 0.3) * 40, s: 0.6 + hash(i + 0.4) }));

export function drawScene(ctx: CanvasRenderingContext2D, w: number, h: number, t: number): void {
  // Camera: a slow lateral drift with a gentle bob — the "dolly shot".
  const camX = Math.sin(t * 0.045) * 2.2 + t * 0.12;
  const camY = 1.35 + Math.sin(t * 0.07) * 0.12;
  const f = Math.min(h * 0.95, w * 0.7);
  // Horizon line; on portrait phones it sits low so the chart shows under the form.
  const hy = h * (h > w * 1.2 ? 0.8 : 0.56) + Math.sin(t * 0.05) * h * 0.012;
  const cx = w * 0.5;
  const px = (x: number, z: number) => cx + ((x - camX) * f) / z;
  const py = (y: number, z: number) => hy - ((y - camY) * f) / z;

  // 1. Night sky.
  const sky = ctx.createLinearGradient(0, 0, 0, h);
  sky.addColorStop(0, "#050507");
  sky.addColorStop(0.55, "#0b0910");
  sky.addColorStop(1, "#040405");
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, w, h);

  // 2. Purple light: one big slow bloom plus a horizon glow.
  ctx.globalCompositeOperation = "lighter";
  const bx = w * (0.62 + Math.sin(t * 0.06) * 0.1);
  const by = h * (0.38 + Math.cos(t * 0.05) * 0.06);
  const br = Math.max(w, h) * 0.6;
  const bloom = ctx.createRadialGradient(bx, by, 0, bx, by, br);
  bloom.addColorStop(0, `rgba(${PURPLE}, 0.30)`);
  bloom.addColorStop(0.45, `rgba(${PURPLE}, 0.10)`);
  bloom.addColorStop(1, `rgba(${PURPLE}, 0)`);
  ctx.fillStyle = bloom;
  ctx.fillRect(0, 0, w, h);

  ctx.save();
  ctx.translate(cx, hy);
  ctx.scale(1, 0.22);
  const hr = w * 0.75;
  const horizon = ctx.createRadialGradient(0, 0, 0, 0, 0, hr);
  horizon.addColorStop(0, `rgba(${PURPLE}, 0.42)`);
  horizon.addColorStop(0.5, `rgba(${PURPLE}, 0.10)`);
  horizon.addColorStop(1, `rgba(${PURPLE}, 0)`);
  ctx.fillStyle = horizon;
  ctx.fillRect(-hr, -hr, hr * 2, hr * 2);
  ctx.restore();
  ctx.globalCompositeOperation = "source-over";

  // 3. Perspective floor grid (white, fading into the distance).
  const far = 60;
  const floor = ctx.createLinearGradient(0, hy, 0, h);
  floor.addColorStop(0, "rgba(255,255,255,0)");
  floor.addColorStop(0.25, "rgba(255,255,255,0.06)");
  floor.addColorStop(1, "rgba(255,255,255,0.16)");
  ctx.strokeStyle = floor;
  ctx.lineWidth = 1;
  ctx.beginPath();
  const startX = Math.floor(camX) - 40;
  for (let k = 0; k <= 80; k++) {
    const x = startX + k;
    ctx.moveTo(px(x, 0.6), py(0, 0.6));
    ctx.lineTo(px(x, far), py(0, far));
  }
  const scroll = (t * 0.55) % 1;
  for (let k = 1; k < far; k++) {
    const z = k - scroll;
    if (z < 0.6) continue;
    const y = py(0, z);
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();

  // 4. Two parallax candle layers floating above the horizon.
  drawCandles(ctx, { w, t, z: 34, base: 3.4, amp: 1.2, step: 0.6, phase: 900, alpha: 0.22, line: false, px, py, camX, f });
  drawCandles(ctx, { w, t, z: 15, base: 2.25, amp: 0.85, step: 0.5, phase: 0, alpha: 0.6, line: true, px, py, camX, f });

  // 5. Dust drifting toward the camera.
  ctx.globalCompositeOperation = "lighter";
  for (const d of DUST) {
    let z = (d.z - t * 0.9) % 42;
    if (z < 1) z += 42;
    const x = d.x + camX * 0.6;
    const sx = px(x, z);
    const sy = py(d.y, z);
    if (sx < -10 || sx > w + 10 || sy < -10 || sy > h + 10) continue;
    const r = Math.max(0.4, (d.s * f) / z / 220);
    const a = Math.min(1, (42 - z) / 30) * 0.5;
    ctx.fillStyle = `rgba(255,255,255,${a.toFixed(3)})`;
    ctx.beginPath();
    ctx.arc(sx, sy, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalCompositeOperation = "source-over";

  // 6. Fog at the horizon + vignette, so the frame reads as one shot.
  const fog = ctx.createLinearGradient(0, hy - h * 0.06, 0, hy + h * 0.1);
  fog.addColorStop(0, "rgba(8,7,12,0)");
  fog.addColorStop(0.5, "rgba(8,7,12,0.55)");
  fog.addColorStop(1, "rgba(8,7,12,0)");
  ctx.fillStyle = fog;
  ctx.fillRect(0, hy - h * 0.06, w, h * 0.16);

  const vr = Math.hypot(w, h) * 0.62;
  const vignette = ctx.createRadialGradient(w / 2, h / 2, vr * 0.35, w / 2, h / 2, vr);
  vignette.addColorStop(0, "rgba(0,0,0,0)");
  vignette.addColorStop(1, "rgba(0,0,0,0.7)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, w, h);
}

type CandleLayer = {
  w: number; t: number; z: number; base: number; amp: number; step: number; phase: number; alpha: number; line: boolean;
  px: (x: number, z: number) => number; py: (y: number, z: number) => number; camX: number; f: number;
};

function drawCandles(ctx: CanvasRenderingContext2D, L: CandleLayer): void {
  const { w, z, base, amp, step, phase, alpha, px, py, camX, f } = L;
  const half = ((w / 2) * z) / f + step * 2;
  const first = Math.floor((camX - half) / step);
  const last = Math.ceil((camX + half) / step);
  const bodyW = Math.max(1, ((step * f) / z) * 0.56);
  const closes: [number, number][] = [];

  for (let i = first; i <= last; i++) {
    const n = i + phase;
    const open = base + price(n - 1) * amp;
    const close = base + price(n) * amp;
    const wick = 0.12 + hash(n + 7) * 0.22;
    const hi = Math.max(open, close) + wick * amp;
    const lo = Math.min(open, close) - wick * amp * 0.8;
    const sx = px(i * step, z);
    // Fade candles out toward both edges of the frame.
    const edge = Math.min(1, Math.min(sx, w - sx) / (w * 0.18));
    if (edge <= 0) continue;
    const up = close >= open;
    const a = alpha * edge;
    ctx.strokeStyle = `rgba(255,255,255,${(a * 0.7).toFixed(3)})`;
    ctx.lineWidth = Math.max(1, bodyW * 0.12);
    ctx.beginPath();
    ctx.moveTo(sx, py(hi, z));
    ctx.lineTo(sx, py(lo, z));
    ctx.stroke();
    const top = py(Math.max(open, close), z);
    const height = Math.max(1.5, py(Math.min(open, close), z) - top);
    if (up) {
      ctx.fillStyle = `rgba(255,255,255,${(a * 0.85).toFixed(3)})`;
      ctx.fillRect(sx - bodyW / 2, top, bodyW, height);
    } else {
      ctx.fillStyle = `rgba(120,120,130,${(a * 0.6).toFixed(3)})`;
      ctx.fillRect(sx - bodyW / 2, top, bodyW, height);
      ctx.strokeStyle = `rgba(255,255,255,${(a * 0.55).toFixed(3)})`;
      ctx.lineWidth = 1;
      ctx.strokeRect(sx - bodyW / 2 + 0.5, top + 0.5, bodyW - 1, Math.max(0.5, height - 1));
    }
    closes.push([sx, py(close, z)]);
  }

  if (!L.line || closes.length < 2) return;

  // Glowing price line: wide faint passes under a crisp core.
  const path = new Path2D();
  closes.forEach(([x, y], k) => (k === 0 ? path.moveTo(x, y) : path.lineTo(x, y)));
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.globalCompositeOperation = "lighter";
  for (const [width, a] of [[14, 0.05], [6, 0.12], [2.5, 0.35]] as const) {
    ctx.strokeStyle = `rgba(${PURPLE}, ${a})`;
    ctx.lineWidth = width;
    ctx.stroke(path);
  }
  ctx.globalCompositeOperation = "source-over";
  ctx.strokeStyle = `rgba(${LAVENDER}, 0.9)`;
  ctx.lineWidth = 1.4;
  ctx.stroke(path);
}
