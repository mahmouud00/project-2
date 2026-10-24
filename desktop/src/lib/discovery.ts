// Finds MYTech servers on the factory network. Inside the desktop app a Rust command sends the
// UDP broadcast "MYTECH_DISCOVER"; in a plain browser discovery is not possible (type the address).
export type FoundServer = { product: string; version: string; host: string; address: string; port: number; scheme: string };

export const inDesktop = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function discover(): Promise<FoundServer[]> {
  if (!inDesktop()) return [];
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<FoundServer[]>("discover_servers", { timeoutMs: 1800 });
}

export function serverUrl(s: FoundServer): string {
  return `${s.scheme || "http"}://${s.address}:${s.port}`;
}
