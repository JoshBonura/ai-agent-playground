// frontend/src/file_read/utils/parseRunjson.ts
export function parseRunJson(content: string): { meta?: any; text: string } {
  const START = "\n[[RUNJSON]]\n";
  const END = "\n[[/RUNJSON]]\n";
  if (!content) return { text: "" };
  const s = content.indexOf(START);
  if (s === -1) return { text: content };
  const e = content.indexOf(END, s + START.length);
  if (e === -1) return { text: content };

  let meta: any | undefined;
  try { meta = JSON.parse(content.slice(s + START.length, e).trim()); } catch {}
  const text = (content.slice(0, s) + content.slice(e + END.length)).trim();
  return { meta, text };
}
