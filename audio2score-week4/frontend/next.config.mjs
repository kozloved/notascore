/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  transpilePackages: ["tone", "@tonejs/midi"],
  // Cursor / local proxies sometimes hit the dev server as 127.0.2.2
  allowedDevOrigins: ["127.0.0.1", "localhost", "127.0.2.2", "127.0.2.3"],
  // Local `next dev` without nginx: browser /api → FastAPI on :8000.
  // Production Compose uses nginx for /api instead.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

export default nextConfig;
