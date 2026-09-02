import type { MetadataRoute } from "next";

import { siteUrl } from "../lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteUrl();
  const paths = [
    "",
    "/how-it-works",
    "/examples",
    "/pricing",
    "/login",
    "/signup",
    "/create",
    "/help",
    "/contact",
    "/privacy",
    "/terms",
    "/cookies",
  ];
  return paths.map((path) => ({
    url: `${base}${path || "/"}`,
    changeFrequency: path === "" ? "weekly" : "monthly",
    priority: path === "" ? 1 : 0.6,
  }));
}
