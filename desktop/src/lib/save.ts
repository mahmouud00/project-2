// Saving a file the program made (Excel, a printout, a library package…). In the desktop program WebView2 drops a
// browser-style download, so the program writes it to the Downloads folder itself and shows it in Explorer.
import { inDesktop } from "./discovery";

/** Saves `data` as `name`; returns where it went (the desktop program), or null (a browser download). */
export async function saveFile(name: string, data: Blob): Promise<string | null> {
  if (inDesktop()) {
    const { invoke } = await import("@tauri-apps/api/core");
    // the bytes go as the raw body (a large file stays a byte buffer), the name in a header
    const path = await invoke<string>("save_download", new Uint8Array(await data.arrayBuffer()),
      { headers: { "x-name": encodeURIComponent(name) } });
    if (!/Android/i.test(navigator.userAgent)) {
      try {
        const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
        await revealItemInDir(path);
      } catch { /* the file is saved; showing it is a convenience */ }
    }
    return path;
  }
  const url = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);          // the file name is only kept for a link that is in the page
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return null;
}
