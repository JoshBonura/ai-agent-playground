/// <reference types="vite/client" />
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_STRIPE_PRICE_PRO_MONTHLY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
