import type { NextConfig } from "next";

// Server-side only (not NEXT_PUBLIC_): the browser never learns the backend address.
// Rewrites are resolved at BUILD time, so set BACKEND_URL before `next build`.
// All API calls go same-origin to /api/v1/* and are proxied here, so session
// cookies stay first-party, SameSite=Strict, and no CORS is needed.
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
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
    return [{ source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
