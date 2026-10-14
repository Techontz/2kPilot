import type { NextConfig } from "next";

// Server-side only (not NEXT_PUBLIC_): the browser never learns the Laravel address.
// Rewrites are resolved at BUILD time, so set BACKEND_URL before `next build`.
// The browser calls /api/* and /sanctum/* on this origin; Next.js proxies them
// to Laravel, so session cookies stay first-party and no CORS is needed.
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8421";

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  // same-origin: Laravel (Sanctum) checks the Referer/Origin of dashboard requests.
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  {
    key: "Content-Security-Policy",
    value: "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
  },
];

/**
 * The app has four sections (Home, Strategies, History, Settings). Older URLs
 * land in the right section/tab. Temporary (307) while the consolidation
 * settles; incoming query strings are passed through (e.g. the Deriv OAuth
 * return to /brokers/new?…). Redirects run before Proxy and the filesystem,
 * so they also apply to client-side <Link> navigations.
 */
export const LEGACY_REDIRECTS: { source: string; destination: string }[] = [
  { source: "/positions", destination: "/history?tab=open" },
  { source: "/orders", destination: "/history?tab=activity" },
  { source: "/journal", destination: "/history?tab=activity" },
  { source: "/analytics", destination: "/history?tab=closed" },
  { source: "/markets", destination: "/charts" },
  { source: "/markets/:symbol", destination: "/charts?symbol=:symbol" },
  { source: "/trade", destination: "/" },
  { source: "/backtesting", destination: "/strategies?tab=backtests" },
  { source: "/backtesting/:id", destination: "/strategies/backtests/:id" },
  { source: "/brokers", destination: "/settings?tab=brokers" },
  { source: "/brokers/new", destination: "/settings/brokers/new" },
  { source: "/risk", destination: "/settings?tab=risk" },
  { source: "/notifications", destination: "/settings?tab=notifications" },
];

// Pin the project root (a stray lockfile higher up would otherwise confuse tracing).
const projectRoot = process.cwd();

const nextConfig: NextConfig = {
  output: "standalone", // minimal self-contained server for Docker
  outputFileTracingRoot: projectRoot,
  turbopack: { root: projectRoot },
  poweredByHeader: false,
  // Dev only: the route indicator badge sat on top of the mobile bottom nav, and
  // every other corner holds the top bar's controls. Hidden; Next.js still shows
  // compile and runtime errors in development.
  devIndicators: false,
  async redirects() {
    return LEGACY_REDIRECTS.map((r) => ({ ...r, permanent: false }));
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      { source: "/sanctum/:path*", destination: `${backendUrl}/sanctum/:path*` },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
