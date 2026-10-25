// Finds MYTech servers on the factory network. Inside the desktop app a Rust command sends the
// UDP broadcast "MYTECH_DISCOVER"; in a plain browser discovery is not possible (type the address).
export type FoundServer = { product: string; version: string; host: string; address: string; port: number; scheme: string };

export const inDesktop = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function discover(): Promise<FoundServer[]> {
  if (!inDesktop()) return [];
  const { invoke } = await import("@tauri-apps/api/core");
  const found = await invoke<FoundServer[]>("discover_servers", { timeoutMs: 1800 });
  // the server PC also answers on 127.0.0.1; show only its network address, which works from every PC
  const loopback = (s: FoundServer) => s.address.startsWith("127.") || s.address === "::1";
  return found.filter((s) => !loopback(s) || !found.some((o) => !loopback(o) && o.host === s.host && o.port === s.port));
}

export function serverUrl(s: FoundServer): string {
  return `${s.scheme || "http"}://${s.address}:${s.port}`;
}
