export async function POST(req: Request){ const b = await req.json(); await grantCredits(b.user, 100) }
