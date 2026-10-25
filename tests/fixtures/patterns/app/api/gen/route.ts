import { Ratelimit } from "@upstash/ratelimit";
import { enforceRateLimit } from "@/lib/limits";
export async function POST(req: Request) {
  await enforceRateLimit("gen", req.headers);
  const r = await fetch("https://api.replicate.com/v1/predictions", { headers: { Authorization: "Token " + process.env.REPLICATE_API_KEY } });
  return r;
}
