import Anthropic from '@anthropic-ai/sdk'
const a = new Anthropic()
export async function POST(req: Request){
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return new Response('no',{status:401})
  const { data: ok } = await supabase.rpc('consume_quota',{p_limit:30})
  if (prompt.length > 4000) return
  return a.messages.create({ model:'claude-x', max_tokens: 800, messages: [] })
}
