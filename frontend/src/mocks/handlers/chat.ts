import { http, HttpResponse } from "msw";
import { apiError, type HandlerOptions } from "./shared";

export function createChatHandlers({ baseUrl }: HandlerOptions) {
  return [
    http.get(`${baseUrl}/chat/config`, () =>
      HttpResponse.json({ configured: false, model: "gemini-flash-latest" }),
    ),
    http.post(`${baseUrl}/chat/config`, () =>
      apiError(503, "CHAT_REQUIRES_BACKEND", "Turn off MSW and connect the real backend to use Gemini."),
    ),
    http.post(`${baseUrl}/chat`, () =>
      apiError(503, "CHAT_REQUIRES_BACKEND", "Turn off MSW and connect the real backend to use Gemini."),
    ),
  ];
}
