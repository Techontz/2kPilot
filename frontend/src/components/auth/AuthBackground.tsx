"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";
import { drawScene, STILL_FRAME_T } from "./authScene";

/**
 * Optional background video for the sign-in / sign-up screens.
 *
 * To use your own footage, put a file in `frontend/public/auth/` and set this to
 * its URL, e.g. `"/auth/background.mp4"` (H.264 MP4 or WebM, ideally < 8 MB,
 * dark footage works best — a dark overlay is added for legibility). It plays
 * muted, looping and inline. If it fails to load, or the visitor prefers
 * reduced motion, the built-in canvas scene is shown instead.
 */
export const AUTH_BACKGROUND_VIDEO: string | null = null;

/** Optional still for the video's first frame (e.g. "/auth/background.jpg"). */
export const AUTH_BACKGROUND_POSTER: string | null = null;

const MAX_DPR = 1.5;
const MAX_PIXELS = 2_600_000; // keeps 4K / large monitors cheap

function subscribeReducedMotion(onChange: () => void) {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}
const reducedMotionSnapshot = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Full-bleed, decorative background. Layers (bottom → top): a CSS poster that
 * paints with the HTML (no flash), then either the video or the canvas scene,
 * which fades in once its first frame is drawn.
 */
export function AuthBackground({ className, videoSrc = AUTH_BACKGROUND_VIDEO, posterSrc = AUTH_BACKGROUND_POSTER }: {
  className?: string; videoSrc?: string | null; posterSrc?: string | null;
}) {
  const reduced = useSyncExternalStore(subscribeReducedMotion, reducedMotionSnapshot, () => false);
  const [videoFailed, setVideoFailed] = useState(false);
  const useVideo = Boolean(videoSrc) && !videoFailed && !reduced;

  return (
    <div aria-hidden className={cn("pointer-events-none overflow-hidden bg-[#050507]", className)} data-motion={reduced ? "still" : "animated"}>
      <Poster src={posterSrc} />
      {useVideo ? (
        <video className="absolute inset-0 size-full object-cover" src={videoSrc ?? undefined} poster={posterSrc ?? undefined}
          autoPlay muted loop playsInline preload="auto" disablePictureInPicture onError={() => setVideoFailed(true)} />
      ) : (
        <SceneCanvas still={reduced} />
      )}
    </div>
  );
}

/** First-paint / fallback still: the same composition in pure CSS. */
function Poster({ src }: { src: string | null }) {
  return (
    <div className="absolute inset-0" style={src ? { backgroundImage: `url(${src})`, backgroundSize: "cover", backgroundPosition: "center" } : undefined}>
      {!src && (
        <>
          <div className="absolute inset-0 bg-[radial-gradient(60%_55%_at_62%_38%,rgb(158_79_224/0.28),transparent_70%),radial-gradient(70%_14%_at_50%_56%,rgb(158_79_224/0.35),transparent_70%),linear-gradient(180deg,#050507,#0b0910_55%,#040405)]" />
          <div className="absolute inset-x-[-50%] top-[56%] bottom-[-30%] origin-top [transform:perspective(420px)_rotateX(68deg)] bg-[linear-gradient(to_right,rgb(255_255_255/0.12)_1px,transparent_1px),linear-gradient(to_bottom,rgb(255_255_255/0.12)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:linear-gradient(to_bottom,transparent,black_40%)]" />
          <div className="absolute inset-0 bg-[radial-gradient(75%_75%_at_50%_50%,transparent_45%,rgb(0_0_0/0.7))]" />
        </>
      )}
    </div>
  );
}

function SceneCanvas({ still }: { still: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d", { alpha: false });
    if (!canvas || !ctx) return;

    let w = 0;
    let h = 0;
    let raf = 0;
    let last = 0;
    let t = STILL_FRAME_T - 6; // start a few seconds in, so the first frame is composed
    let running = false;

    const render = () => {
      if (w === 0 || h === 0) return;
      drawScene(ctx, w, h, still ? STILL_FRAME_T : t);
      canvas.dataset.ready = "true";
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR, Math.sqrt(MAX_PIXELS / Math.max(1, w * h)));
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      ctx.setTransform(canvas.width / Math.max(1, w), 0, 0, canvas.height / Math.max(1, h), 0, 0);
      render();
    };

    const frame = (now: number) => {
      // Clamp the step so returning to the tab doesn't jump the camera.
      t += Math.min(0.05, last ? (now - last) / 1000 : 0);
      last = now;
      render();
      raf = requestAnimationFrame(frame);
    };
    const start = () => {
      if (running || still || document.hidden) return;
      running = true;
      last = 0;
      raf = requestAnimationFrame(frame);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };
    const onVisibility = () => (document.hidden ? stop() : start());

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();
    start();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [still]);

  return <canvas ref={ref} className="absolute inset-0 size-full opacity-0 transition-opacity duration-700 data-[ready=true]:opacity-100" />;
}
