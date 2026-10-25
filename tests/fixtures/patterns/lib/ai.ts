import { streamText } from "ai";
export function runChat(messages: any[]) { return streamText({ model: m, messages, maxOutputTokens: 500 }); }
