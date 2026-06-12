import { NextRequest } from "next/server";
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

export async function POST(req: NextRequest) {
  try {
    const { messages, systemPrompt } = await req.json();

    const stream = client.messages.stream({
      model: "claude-sonnet-4-6",
      max_tokens: 64000,
      system: systemPrompt,
      messages,
    });

    // The frontend uses `@openuidev`'s `openAIReadableStreamAdapter`, which
    // parses newline-delimited OpenAI chat-completion chunks and reads
    // `choices[0].delta.content`. Translate Anthropic's text deltas into that
    // shape so the frontend stays unchanged.
    const encoder = new TextEncoder();
    const readable = new ReadableStream<Uint8Array>({
      async start(controller) {
        const send = (chunk: unknown) =>
          controller.enqueue(encoder.encode(JSON.stringify(chunk) + "\n"));
        try {
          for await (const event of stream) {
            if (
              event.type === "content_block_delta" &&
              event.delta.type === "text_delta"
            ) {
              send({ choices: [{ delta: { content: event.delta.text } }] });
            }
          }
          send({ choices: [{ delta: {}, finish_reason: "stop" }] });
          controller.close();
        } catch (err) {
          controller.error(err);
        }
      },
    });

    return new Response(readable, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  } catch (err) {
    console.error(err);
    const message = err instanceof Error ? err.message : "Unknown error";
    return new Response(JSON.stringify({ error: message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
}
