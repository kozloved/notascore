/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Cursor / local proxies sometimes hit the dev server as 127.0.2.2
  allowedDevOrigins: ["127.0.0.1", "localhost", "127.0.2.2", "127.0.2.3"],
  // Local next:3000 has no nginx — proxy /api → FastAPI so NEXT_PUBLIC_API_URL=/api works
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
