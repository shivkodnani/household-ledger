import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  ...(process.env.NODE_ENV === "development"
    ? {
        async rewrites() {
          return [
            { source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" },
            { source: "/files/:path*", destination: "http://127.0.0.1:8000/files/:path*" },
          ];
        },
      }
    : {}),
};

export default nextConfig;
