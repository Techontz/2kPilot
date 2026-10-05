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

// Pin the project root (a stray lockfile higher up would otherwise confuse tracing).
const projectRoot = process.cwd();

const nextConfig: NextConfig = {
  output: "standalone", // minimal self-contained server for Docker
  outputFileTracingRoot: projectRoot,
  turbopack: { root: projectRoot },
  poweredByHeader: false,
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
