// Keeps Inkling 2 Mini's thinking in its own context from one tool step to the next.
//
// The lab's Anthropic-shaped route streams each thinking block with an empty signature, and
// OpenCode's Anthropic driver replays only signed thinking. So on every step the model sees its
// earlier tool calls and none of the reasons behind them, where a Claude model sees its own. This
// plugin adds a placeholder signature to each unsigned thinking block in the lab's stream, so
// OpenCode stores the block and sends it back. The lab accepts the placeholder.

const PROVIDER = "thinkingmachines"
const PLACEHOLDER = "opencode-unsigned"

function signStream(body) {
  const decoder = new TextDecoder()
  const encoder = new TextEncoder()
  const thinking = new Set()
  let buffer = ""
  const rewrite = (frame) => {
    const line = frame.split("\n").find((l) => l.startsWith("data: "))
    if (!line) return frame
    let event
    try {
      event = JSON.parse(line.slice(6))
    } catch {
      return frame
    }
    if (event.type === "content_block_start" && event.content_block?.type === "thinking" && !event.content_block.signature) {
      thinking.add(event.index)
    }
    if (event.type === "content_block_stop" && thinking.has(event.index)) {
      thinking.delete(event.index)
      const delta = { type: "content_block_delta", index: event.index, delta: { type: "signature_delta", signature: PLACEHOLDER } }
      return `event: content_block_delta\ndata: ${JSON.stringify(delta)}\n\n${frame}`
    }
    return frame
  }
  return body.pipeThrough(
    new TransformStream({
      transform(chunk, controller) {
        buffer += decoder.decode(chunk, { stream: true })
        let cut
        while ((cut = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, cut + 2)
          buffer = buffer.slice(cut + 2)
          controller.enqueue(encoder.encode(rewrite(frame)))
        }
      },
      flush(controller) {
        if (buffer) controller.enqueue(encoder.encode(rewrite(buffer)))
      },
    }),
  )
}

export default {
  id: "inkling-thinking",
  async setup(ctx) {
    await ctx.session.hook("http.response", (event) => {
      if (event.model.providerID !== PROVIDER) return
      const type = event.response.headers.get("content-type") || ""
      if (!event.response.body || !type.includes("text/event-stream")) return
      event.response = new Response(signStream(event.response.body), {
        status: event.response.status,
        statusText: event.response.statusText,
        headers: event.response.headers,
      })
    })
  },
}
