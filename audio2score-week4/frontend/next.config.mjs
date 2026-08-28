/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  transpilePackages: ["tone", "@tonejs/midi"],
  // Cursor / local proxies sometimes hit the dev server as 127.0.2.2
  allowedDevOrigins: ["127.0.0.1", "localhost", "127.0.2.2", "127.0.2.3"],
  // Fallback when the app/api/[...path] route is not used (e.g. some hosts).
  // Railway and `next dev` prefer the route handler so BACKEND_URL is runtime.
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
