import { API_BASE } from "../services/http";
import { listMessages, updateChatLast } from "../data/chatApi";
import { stripRunJson } from "../shared/lib/runjson";

const TITLE_MAX_WORDS = 6;
// ⏹ stopped (server emits as a final line sometimes)
const STOP_SENTINEL_RE = /(?:\r?\n)?(?:\u23F9|\\u23F9)\s+stopped(?:\r?\n)?$/u;

function sanitizeTitle(raw: string, maxWords = TITLE_MAX_WORDS) {
  let t = raw.split(/\r?\n/)[0] ?? "";
  t = t.replace(/[^\p{L}\p{N} ]+/gu, " ");
  t = t.replace(/\s+/g, " ").trim();
  t = t.split(" ").slice(0, maxWords).join(" ").trim();
  return t;
}

export function useRetitle(enabled = true) {
  async function retitleNow(sessionId: string, latestAssistant: string) {
    if (!enabled) return;

    try {
      // Build a minimal transcript to title on
      const rows = await listMessages(sessionId);
      const textDump = rows
        .map((r) => `${r.role === "user" ? "User" : "Assistant"}: ${r.content}`)
        .join("\n");

      const res = await fetch(`${API_BASE}/api/ai/generate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: `${sessionId}::titlebot`,
          messages: [
            { role: "system", content: "You output ultra-concise, neutral chat titles and nothing else." },
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

      // ✅ Parse SSE properly: ignore 'event: ...' and keep only 'data:' payloads
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      const lines: string[] = [];

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) {
          buf += decoder.decode(value, { stream: true });

          // Process complete lines
          let idx: number;
          while ((idx = buf.indexOf("\n")) !== -1) {
            const line = buf.slice(0, idx).replace(/\r$/, "");
            buf = buf.slice(idx + 1);

            if (!line) continue;
            if (line.startsWith("event:")) {
              // ignore 'event: open' / 'event: hb' etc.
              continue;
            }
            if (line.startsWith("data:")) {
              const payload = line.slice(5).trimStart();
              if (payload.includes("⏹ stopped")) {
                // stop immediately on sentinel
                buf = "";
                break;
              }
              lines.push(payload);
            }
          }
        }
      }

      // Combine, strip runjson blocks & final sentinel
      const raw = lines.join("\n");
      const { text } = stripRunJson(raw);
      const cleaned = text.replace(STOP_SENTINEL_RE, "").trim();
      const title = sanitizeTitle(cleaned);
      if (!title) return;

      await updateChatLast(sessionId, latestAssistant, title).catch(() => {});
      try {
        window.dispatchEvent(new CustomEvent("chats:refresh"));
      } catch {}
    } catch (e) {
      console.warn("retitleNow failed:", e);
    }
  }

  return { retitleNow };
}
