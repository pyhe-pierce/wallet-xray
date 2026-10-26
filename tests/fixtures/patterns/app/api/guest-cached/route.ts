import { cookies } from "next/headers";
import { guestCached } from "@/lib/guest-ai-cache";
export async function POST(req: Request) {
  const isGuest = (await cookies()).get("guestMode")?.value === "true";
  if (!isGuest) { const { data: { user } } = await supabase.auth.getUser(); if (!user) return new Response("no", { status: 401 }); if (count >= limit) return new Response("x", { status: 429 }); }
  const generate = async () => (await fetch(`https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=${process.env.GEMINI_API_KEY}`, { body: JSON.stringify({ generationConfig: { maxOutputTokens: 1000 } }) })).json();
  const out = isGuest ? await guestCached("demo:v1", generate) : await generate();
  return Response.json(out);
}
