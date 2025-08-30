// frontend/src/file_read/hooks/useRetitle.ts
import { API_BASE } from "../services/http";
import { listMessages, updateChatLast } from "../data/chatApi";
import { stripRunJson } from "../shared/lib/runjson";

const TITLE_MAX_WORDS = 6;

function sanitizeTitle(raw: string, maxWords = TITLE_MAX_WORDS) {
  let t = (raw.split(/\r?\n/)[0] ?? "");
  t = t.replace(/[^\p{L}\p{N} ]+/gu, " ");
  t = t.replace(/\s+/g, " ").trim();
  t = t.split(" ").slice(0, maxWords).join(" ").trim();
  return t;
}

export function useRetitle(enabled = true) {
  async function retitleNow(sessionId: string, latestAssistant: string) {
    console.log("1")
    if (!enabled) return;

    try {
      // Build a minimal transcript to title on
      const rows = await listMessages(sessionId);
      const textDump = rows
        .map((r) => `${r.role === "user" ? "User" : "Assistant"}: ${r.content}`)
        .join("\n");

      // Ask the local model for a very short title
      const res = await fetch(`${API_BASE}/api/ai/generate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: `${sessionId}::titlebot`,
          messages: [
            {
              role: "system",
              content: "You output ultra-concise, neutral chat titles and nothing else.",
            },
            {
              role: "user",
              content:
                "Write ONE short title summarizing the conversation below.\n" +
                "Rules: at most 6 words — sentence or title case — no punctuation — no emojis — no quotes — return ONLY the title\n\n" +
                textDump +
                "\n\nTitle:",
            },
          ],
          max_tokens: 24,
          temperature: 0.2,
          top_p: 0.9,
        }),
      });

      if (!res.ok || !res.body) return;

      // Gather the streamed text + strip runjson
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let raw = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) raw += decoder.decode(value, { stream: true });
      }

      const { text } = stripRunJson(raw);
      const title = sanitizeTitle(text);
      if (!title) return;

      // Save title + lastMessage (lastMessage stays the full assistant text)
      await updateChatLast(sessionId, latestAssistant, title).catch(() => {});
      // Nudge sidebar so it shows new title immediately
      try {
        window.dispatchEvent(new CustomEvent("chats:refresh"));
      } catch {}
    } catch (e) {
      console.warn("retitleNow failed:", e);
    }
  }

  return { retitleNow };
}
