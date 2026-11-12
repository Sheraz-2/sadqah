// Security headers + same-origin proxy to the FastAPI backend (so session cookies are first-party).
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const isDev = process.env.NODE_ENV !== "production";

const csp = [
  "default-src 'self'",
  // Next.js needs inline scripts for hydration; PayPal's SDK loads from paypal.com.
  `script-src 'self' 'unsafe-inline' ${isDev ? "'unsafe-eval' " : ""}https://www.paypal.com https://*.paypal.com`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://*.paypal.com https://*.paypalobjects.com",
  "font-src 'self' data:",
  `connect-src 'self' https://*.paypal.com https://*.paypalobjects.com${isDev ? " ws:" : ""}`,
  "frame-src https://*.paypal.com",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self' https://*.paypal.com",
  "object-src 'none'",
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  // The dev/production server proxies /api to FastAPI. A local AI model on a CPU can take longer than the proxy's default wait, which
  // would show an error while the answer is still being written; allow up to 3 minutes (the assistant has its own, shorter limits).
  experimental: { proxyTimeout: 180_000 },
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
      { source: "/media/:path*", destination: `${BACKEND_URL}/api/v1/media/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(self), microphone=(self), geolocation=(), payment=(self)" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
        ],
      },
    ];
  },
};

export default nextConfig;
