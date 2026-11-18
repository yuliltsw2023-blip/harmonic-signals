// Kunci password sederhana (HTTP Basic Auth) untuk seluruh website.
// Password = env SITE_PASSWORD di Vercel; username bebas.
export const config = { matcher: "/:path*" };

export default function middleware(request) {
  const expected = process.env.SITE_PASSWORD;
  if (!expected) {
    return new Response("SITE_PASSWORD belum di-set", { status: 500 });
  }
  const auth = request.headers.get("authorization") || "";
  if (auth.startsWith("Basic ")) {
    try {
      const decoded = atob(auth.slice(6));
      const pass = decoded.slice(decoded.indexOf(":") + 1);
      if (pass === expected) return; // lanjut ke halaman / API
    } catch (_) {
      /* header rusak → minta login lagi */
    }
  }
  return new Response("Login dibutuhkan", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Gold Briefing", charset="UTF-8"' },
  });
}
