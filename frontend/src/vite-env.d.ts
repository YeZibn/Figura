/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CHARTAGENT_MODE?: 'mock' | 'gateway'
  readonly VITE_CHARTAGENT_GATEWAY_URL?: string
  readonly VITE_FIGURA_MODE?: 'true' | 'false'
  readonly VITE_FIGURA_GATEWAY_URL?: string
  readonly VITE_DEV_PORT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
