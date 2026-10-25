import { auth } from "@/app/auth";
import { runChat } from "@/lib/ai";
export async function POST(req: Request) {
  const session = await auth();
  if (!session) return new Response("no", { status: 401 });
  if (count > entitlements.maxMessagesPerHour) return new Response("slow", { status: 429 });
  return runChat([]);
}
