import OpenAI from 'openai'
const client = new OpenAI({ apiKey: "sk-proj-FAKEKEYFORTESTINGONLY0000000000" })
export async function POST(req: Request){
  const { model, prompt } = await req.json()
  return client.chat.completions.create({ model, messages:[{role:'user',content:prompt}] })
}
