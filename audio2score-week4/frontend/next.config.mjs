/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Cursor Cloud / tunneled preview hosts need /_next assets in `next dev`.
  allowedDevOrigins: [
    "127.0.0.1",
    "*.cursor.sh",
    "*.cursor.com",
    "*.cursorsh.com",
  ],
};

export default nextConfig;
