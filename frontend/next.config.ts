import type { NextConfig } from "next";

const config: NextConfig = {
  basePath: "/app/workbench",
  output: "export",
  trailingSlash: true,
  poweredByHeader: false,
  devIndicators: false,
};
export default config;
