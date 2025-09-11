// frontend/src/file_read/auth/ForgotPassword.tsx
import { useState } from "react";
import { postJSON } from "../services/http";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSent(false);
    setSubmitting(true);
    try {
      // Backend should implement: POST /auth/forgot  { email }
      // Behavior suggestion:
      //  - If SMTP configured: send email with reset link/token
      //  - If offline: generate token and print reset URL to server logs (admin shares it)
      await postJSON("/auth/forgot", { email: email.trim().toLowerCase() });
      setSent(true);
    } catch (e: any) {
      // Common cases: 404 if endpoint not implemented, or 400/422 for bad email
      const msg = (e?.message as string) || "";
      if (/HTTP 404/i.test(msg)) {
        setErr(
          "Password reset isn’t enabled on this box. Ask the admin to reset your password.",
        );
      } else {
        setErr(
          msg.replace(/^HTTP \d+\s*–\s*/, "") || "Could not send reset request",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h1 className="text-xl font-semibold text-center">Reset password</h1>

      <div className="space-y-1">
        <label className="block text-sm text-gray-700">Email</label>
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          type="email"
          inputMode="email"
          autoComplete="email"
          required
          className="w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:ring-2 focus:ring-black"
          placeholder="you@example.com"
        />
      </div>

      {sent && (
        <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
          If password reset is enabled, a link has been sent (or printed in the
          server logs if email isn’t configured). Contact your admin if you
          don’t receive it.
        </div>
      )}

      {err && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {err}
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-lg bg-black text-white py-2.5 font-medium disabled:opacity-60"
      >
        {submitting ? "Sending…" : "Send reset request"}
      </button>
    </form>
  );
}
