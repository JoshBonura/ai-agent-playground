import { appendMessage, updateChatLast } from "../../../hooks/data/chatApi";
import type { RunJson } from "../../../shared/lib/runjson";
import { MET_START, MET_END } from "../../../shared/lib/runjson";

export async function persistAssistantTurn(
  sid: string,
  finalText: string,
  json: RunJson | null
) {
  let toPersist = finalText;
  if (json) {
    toPersist = `${finalText}\n${MET_START}\n${JSON.stringify(json)}\n${MET_END}\n`;
  }
  await appendMessage(sid, "assistant", toPersist).catch(() => {});
  await updateChatLast(sid, finalText, "").catch(() => {});
}
