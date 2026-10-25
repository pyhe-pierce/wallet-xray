import OpenAI from "openai";
export async function POST(req: Request) {
  const profile = await getServerProfile();
  const openai = new OpenAI({ apiKey: profile.openai_api_key });
  return openai.chat.completions.create({ model: "x", messages: [] });
}
