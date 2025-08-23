import { appendMessage, updateChatLast } from "../../data/chatApi";
import type { RunJson } from "../../../shared/lib/runjson";
import { MET_START, MET_END } from "../../../shared/lib/runjson";

/**
 * Persist assistant turn; returns the new server message id (or null).
 */
export async function persistAssistantTurn(
  sid: string,
  finalText: string,
  json: RunJson | null
): Promise<number | null> {
  let toPersist = finalText;
  if (json) {
    toPersist = `${finalText}\n${MET_START}\n${JSON.stringify(json)}\n${MET_END}\n`;
  }
  try {
    const row = await appendMessage(sid, "assistant", toPersist);
    await updateChatLast(sid, finalText, "").catch(() => {});
    return row?.id != null ? Number(row.id) : null;
  } catch {
    return null;
  }
}
