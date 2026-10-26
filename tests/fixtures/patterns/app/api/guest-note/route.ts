import { cookies } from "next/headers";
export async function POST(req: Request) {
  const isGuest = (await cookies()).get("guestMode")?.value === "true";
  if (!isGuest) {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return new Response("no", { status: 401 });
    if (count >= limit) return new Response("limit", { status: 429 });
  }
  const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=${process.env.GEMINI_API_KEY}`, { method: "POST", body: JSON.stringify({ generationConfig: { maxOutputTokens: 65536 } }) });
  return r;
}
