import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Cloud Run image (web/Dockerfile copies
  // .next/standalone + .next/static + public and runs `node server.js`).
  output: "standalone",
  // Node-only SDKs are required at runtime instead of being bundled: they pull
  // in gRPC/native-ish deps and read ADC from the environment. firebase-admin is
  // already in Next's default external list; BigQuery is not.
  serverExternalPackages: ["@google-cloud/bigquery"],
};

export default nextConfig;
