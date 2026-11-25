// Author: Ching Kao
// Student ID: 85768427
import { http, HttpResponse } from "msw";
import { apiError, type HandlerOptions } from "./shared";

export function createChatHandlers({ baseUrl }: HandlerOptions) {
  return [
    http.get(`${baseUrl}/llm/records`, () => HttpResponse.json([])),
    http.get(`${baseUrl}/chat/config`, ({ request }) => {
      const provider = new URL(request.url).searchParams.get("provider") ?? "gemini";
      if (provider === "codex") {
        return HttpResponse.json({ configured: false, provider, model: "gpt-5.6-luna", effort: "low" });
      }
      return HttpResponse.json({ configured: false, provider, model: provider === "groq" ? "openai/gpt-oss-120b" : "gemini-flash-latest" });
    }),
    http.post(`${baseUrl}/chat/config`, () =>
      apiError(503, "CHAT_REQUIRES_BACKEND", "Turn off MSW and connect the real backend to use chat."),
    ),
    http.post(`${baseUrl}/chat/model`, () =>
      apiError(503, "CHAT_REQUIRES_BACKEND", "Turn off MSW and connect the real backend to change the model."),
    ),
    http.post(`${baseUrl}/chat`, () =>
      apiError(503, "CHAT_REQUIRES_BACKEND", "Turn off MSW and connect the real backend to use chat."),
    ),
  ];
}
