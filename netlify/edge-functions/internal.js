// Server-side gate for the internal pages (docs + design plans).
//
// Real protection: Netlify's edge refuses to serve these paths' bytes until a
// valid auth cookie is present — unlike the old client-side gate, which shipped
// the page and merely hid it. The directory and all other pages stay public.
//
// One shared password, read from the INTERNAL_PW env var (set in the Netlify
// UI — never in the repo). The auth cookie is an HMAC of a constant keyed by
// INTERNAL_PW, so it can't be forged without the password and never contains it.
// HttpOnly + Secure + SameSite=Lax; 12-hour lifetime.
//
// This one function also serves the login POST (/internal-auth) and logout
// (/internal-logout) so there's a single place to reason about auth.

const COOKIE = "bil_auth";
const MSG = "bil-internal-v1"; // constant signed with the password
const MAX_AGE = 60 * 60 * 12;  // 12h

async function token(pw) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(pw), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(MSG));
  return btoa(String.fromCharCode(...new Uint8Array(sig)));
}

function readCookie(req, name) {
  const raw = req.headers.get("cookie") || "";
  const m = raw.match(new RegExp("(?:^|; )" + name + "=([^;]+)"));
  return m ? decodeURIComponent(m[1]) : null;
}

// Only allow same-site relative redirect targets (no open redirect).
function safeNext(next) {
  return (typeof next === "string" && next.startsWith("/") && !next.startsWith("//")) ? next : "/";
}

export default async (request, context) => {
  const url = new URL(request.url);
  const path = url.pathname;
  const PW = Deno.env.get("INTERNAL_PW");

  // Fail closed on misconfiguration rather than exposing the page.
  if (!PW) {
    return new Response("Internal area is not configured (INTERNAL_PW is missing).", {
      status: 500, headers: { "content-type": "text/plain" },
    });
  }
  const expected = await token(PW);

  // ── Logout ──────────────────────────────────────────────────────────────
  if (path === "/internal-logout") {
    const headers = new Headers({ Location: "/internal-login.html" });
    headers.append("Set-Cookie",
      `${COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`);
    return new Response(null, { status: 302, headers });
  }

  // ── Login (form POST from internal-login.html) ──────────────────────────
  if (path === "/internal-auth") {
    if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });
    const form = await request.formData();
    const next = safeNext(form.get("next"));
    if (form.get("password") === PW) {
      const headers = new Headers({ Location: next });
      headers.append("Set-Cookie",
        `${COOKIE}=${encodeURIComponent(expected)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${MAX_AGE}`);
      return new Response(null, { status: 302, headers });
    }
    const headers = new Headers({
      Location: `/internal-login.html?e=1&next=${encodeURIComponent(next)}`,
    });
    return new Response(null, { status: 302, headers });
  }

  // ── Protected pages: require a valid cookie, else send to login ──────────
  if (readCookie(request, COOKIE) === expected) {
    return context.next();
  }
  const headers = new Headers({
    Location: `/internal-login.html?next=${encodeURIComponent(path)}`,
  });
  return new Response(null, { status: 302, headers });
};

// Gate the internal pages + own the auth endpoints. Extensionless variants are
// included in case Netlify "pretty URLs" is on. The login page itself is not
// listed, so it stays reachable.
export const config = {
  path: [
    "/docs.html", "/docs",
    "/plan-landing-pages.html", "/plan-landing-pages",
    "/internal-auth", "/internal-logout",
  ],
};
