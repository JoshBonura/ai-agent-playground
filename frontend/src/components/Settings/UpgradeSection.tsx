import { useEffect, useMemo, useState } from "react";
import { getBillingStatus, openPortal, startCheckout } from "../../api/billing";
import { buildUrl } from "../../services/http";

type Props = { userEmail?: string | null };

function openExternal(url: string) {
  // @ts-ignore
  if (window?.electron?.openExternal) return window.electron.openExternal(url);
  window.open(url, "_blank", "noopener,noreferrer");
}

export default function UpgradeSection({ userEmail }: Props) {
  const [billing, setBilling] = useState<null | {
    status: string;
    current_period_end: number;
  }>(null);
  const [license, setLicense] = useState<{
    plan: string;
    valid: boolean;
    exp?: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const isPro = useMemo(() => {
    const s = (billing?.status || "").toLowerCase();
    const billActive = s === "active" || s === "trialing" || s === "past_due";
    const licActive =
      Boolean(license?.valid) &&
      (license?.plan || "pro").toLowerCase() !== "free";
    return billActive || licActive;
  }, [billing, license]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const [b, l] = await Promise.all([
          getBillingStatus(), // cookie-auth; 401 if not logged in
          fetch(buildUrl("/license/status"), {
            method: "GET",
            credentials: "include",
            headers: { Accept: "application/json" },
          }).then((r) => {
            if (!r.ok) throw new Error("license status failed");
            return r.json();
          }),
        ]);
        if (mounted) {
          setBilling(b);
          setLicense(l);
        }
      } catch (e: any) {
        if (mounted) setErr(e?.message || "Failed to load billing/license");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [userEmail]); // re-run when user changes

  async function handleUpgrade() {
    if (!userEmail) {
      setErr("Please sign in to upgrade.");
      return;
    }
    try {
      setErr(null);
      const priceId =
        (import.meta.env.VITE_STRIPE_PRICE_PRO_MONTHLY as string | undefined) ||
        undefined;
      const { url } = await startCheckout(priceId);
      openExternal(url);
    } catch (e: any) {
      setErr(e?.message || "Could not start checkout");
    }
  }

  async function handleManage() {
    if (!userEmail) {
      setErr("Please sign in to manage billing.");
      return;
    }
    try {
      setErr(null);
      const { url } = await openPortal();
      openExternal(url);
    } catch (e: any) {
      setErr(e?.message || "Could not open billing portal");
    }
  }

  return (
    <div className="rounded-2xl border p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="font-semibold">Upgrade</div>
        <span
          className={
            "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs " +
            (isPro ? "bg-green-600 text-white" : "bg-gray-200 text-gray-800")
          }
        >
          {isPro ? "Pro (active)" : loading ? "Loading…" : "Free"}
        </span>
      </div>

      {err && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {err}
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <PlanCard
          title="Free"
          price="$0"
          features={["Local model", "Basic settings"]}
          ctaLabel="Current Plan"
          ctaDisabled
        />
        <PlanCard
          title="Pro"
          price="$12/mo"
          subtitle="or $96/year"
          features={[
            "Pro features via license",
            "Priority updates",
            "Manage billing in portal",
          ]}
          ctaLabel={isPro ? "Manage Billing" : "Go Pro"}
          onClick={isPro ? handleManage : handleUpgrade}
          highlight
        />
      </div>

      <div className="mt-6 rounded-xl border bg-gray-50 p-3 text-xs text-gray-700">
        <div className="font-medium mb-1">License</div>
        <div>
          Plan: <strong>{license?.plan ?? "free"}</strong>{" "}
          {license?.valid === false && "(invalid/expired)"}
        </div>
        {license?.exp ? (
          <div>Exp: {new Date(license.exp * 1000).toLocaleDateString()}</div>
        ) : null}
        {userEmail && (
          <div className="mt-2 text-gray-600">
            Signed in as <strong>{userEmail}</strong>
          </div>
        )}
      </div>
    </div>
  );
}

function PlanCard({
  title,
  price,
  subtitle,
  features,
  ctaLabel,
  ctaDisabled,
  onClick,
  highlight,
}: {
  title: string;
  price: string;
  subtitle?: string;
  features: string[];
  ctaLabel: string;
  ctaDisabled?: boolean;
  onClick?: () => void;
  highlight?: boolean;
}) {
  return (
    <div
      className={
        "rounded-2xl border bg-white p-6 shadow-sm " +
        (highlight ? "ring-2 ring-indigo-500" : "")
      }
    >
      <div className="mb-2 flex items-center justify-between">
        <div className="text-lg font-semibold">{title}</div>
        {highlight && (
          <span className="rounded-full bg-indigo-100 px-2 py-1 text-xs text-indigo-700">
            Best Value
          </span>
        )}
      </div>
      <div className="mb-1 text-3xl font-bold">{price}</div>
      {subtitle && <div className="mb-4 text-sm text-gray-500">{subtitle}</div>}
      <ul className="mb-6 space-y-2 text-sm text-gray-700">
        {features.map((f) => (
          <li key={f}>• {f}</li>
        ))}
      </ul>
      <button
        disabled={ctaDisabled}
        onClick={onClick}
        className={
          "w-full rounded-xl px-4 py-2 font-medium " +
          (ctaDisabled
            ? "cursor-not-allowed border text-gray-500"
            : highlight
              ? "bg-indigo-600 text-white hover:bg-indigo-700"
              : "border hover:bg-gray-50")
        }
      >
        {ctaLabel}
      </button>
    </div>
  );
}
