import { cookies } from "next/headers";
export async function POST(req: Request) {
  const isGuest = (await cookies()).get("guestMode")?.value === "true";
  if (isGuest) {
    return Response.json({ error: "Sign up first" }, { status: 403 });
  }
  if (!isGuest) { const { data: { user } } = await supabase.auth.getUser(); if (!user) return new Response("no", { status: 401 }); if (count >= limit) return new Response("x", { status: 429 }); }
  return fetch(`https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=${process.env.GEMINI_API_KEY}`, { body: JSON.stringify({ generationConfig: { maxOutputTokens: 1000 } }) });
}
