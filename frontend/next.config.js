/** @type {import('next').NextConfig} */
const demo = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// GitHub Pages build: static export served from /<repo-name>. Docker build: standalone server.
module.exports = {
  output: demo ? "export" : "standalone",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  trailingSlash: demo,
  images: { unoptimized: true },
  reactStrictMode: true,
  poweredByHeader: false,
};
