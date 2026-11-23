import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: { root: process.cwd() },
  async rewrites() {
    const apiOrigin = process.env.ARCHIVE_API_ORIGIN ?? "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      { source: "/auth/:path*", destination: `${apiOrigin}/auth/:path*` },
    ];
  },
};

export default nextConfig;
