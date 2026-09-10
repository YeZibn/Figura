/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CHARTAGENT_MODE?: 'mock' | 'gateway'
  readonly VITE_CHARTAGENT_GATEWAY_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
