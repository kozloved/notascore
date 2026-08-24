/**
 * Stub Worker so Git-connected Workers Builds can deploy.
 * NotaScore itself is not served from here.
 */
export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/health" || url.pathname === "/") {
      return Response.json({
        status: "ok",
        service: "notascore",
        runtime: "cloudflare-worker-stub",
        note:
          "NotaScore runs as FastAPI + Next.js behind a Cloudflare Tunnel, not this Worker.",
      });
    }
    return Response.redirect("https://notascore.com/", 302);
  },
};
