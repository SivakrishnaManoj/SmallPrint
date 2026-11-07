/**
 * Stream SSE events from /analyse via fetch + ReadableStream.
 * Uses POST so we can send the request body.
 * Postcode is explicitly excluded from the outgoing request.
 */
import type { AnalyseRequest, StreamCard } from "./types";

export async function* streamAnalyse(
  serverUrl: string,
  request: AnalyseRequest,
  signal?: AbortSignal
): AsyncGenerator<StreamCard | "done"> {
  // Assertion: postcode must never appear in the request body
  const body = JSON.stringify(request);
  if (typeof request === "object" && "postcode" in (request as unknown as Record<string, unknown>)) {
    throw new Error("postcode must not be included in server requests");
  }

  const response = await fetch(`${serverUrl}/analyse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`Server error: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const raw of lines) {
      const line = raw.trim();
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const dataStr = line.slice(5).trim();
        try {
          const data = JSON.parse(dataStr);
          if (currentEvent === "card") {
            yield data as StreamCard;
          } else if (currentEvent === "done") {
            yield "done";
            return;
          }
        } catch {
          // malformed event — skip
        }
        currentEvent = "";
      }
    }
  }
}
