'use client'
import { GoogleGenAI } from '@google/genai'
const ai = new GoogleGenAI({ apiKey: process.env.NEXT_PUBLIC_GEMINI_API_KEY })
export default function Chat(){ ai.models.generateContent({model:'x',contents:'hi'}) }
