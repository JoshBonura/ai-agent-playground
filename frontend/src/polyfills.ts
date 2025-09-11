// src/polyfills.ts
(function () {
  const g: any = typeof globalThis !== "undefined" ? globalThis : window;

  if (!g.crypto) g.crypto = {};

  if (!g.crypto.getRandomValues) {
    g.crypto.getRandomValues = (arr: Uint8Array) => {
      for (let i = 0; i < arr.length; i++)
        arr[i] = Math.floor(Math.random() * 256);
      return arr;
    };
  }

  if (!g.crypto.randomUUID) {
    g.crypto.randomUUID = function () {
      const bytes = new Uint8Array(16);
      g.crypto.getRandomValues(bytes);
      // RFC 4122 v4
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      const hex = Array.from(bytes, (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    };
  }
})();
