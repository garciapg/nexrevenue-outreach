// Email open tracking pixel. GET /functions/v1/nr-open?t=<lead id>&s=<step> returns a 1x1 gif and records
// the open in outreach.opens. Public on purpose (verify_jwt off): it only stores lead id, step, time and
// user agent, never returns data, and ignores anything that is not a known lead.
import postgres from "npm:postgres@3.4.4";

const sql = postgres(Deno.env.get("SUPABASE_DB_URL")!, { max: 1, prepare: false });
const GIF = Uint8Array.from(atob("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"), (c) => c.charCodeAt(0));
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const lead = url.searchParams.get("t") ?? "";
  const step = parseInt(url.searchParams.get("s") ?? "1", 10);
  if (UUID.test(lead) && step >= 1 && step <= 10) {
    try {
      const ua = (req.headers.get("user-agent") ?? "").slice(0, 200);
      await sql`insert into outreach.opens (lead_id, step, ua)
                select ${lead}::uuid, ${step}, ${ua}
                where exists (select 1 from outreach.leads where id = ${lead}::uuid)`;
    } catch (_) { /* never break the image */ }
  }
  return new Response(GIF, {
    headers: { "Content-Type": "image/gif", "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0" },
  });
});
