// The technician's position while a job is on the way / arrived. In the phone app it comes from the phone's
// GPS (native plugin, works with the factory's http server too); in a browser it needs https.
import { inDesktop } from "./discovery";

export type Fix = { latitude: number; longitude: number; accuracy: number | null };
export const isPhone = () => /android|iphone|ipad/i.test(navigator.userAgent);

/** Starts watching; returns a stop function. `onError` gets an Arabic message. */
export async function watchPosition(onFix: (f: Fix) => void, onError: (msg: string) => void): Promise<() => void> {
  const opts = { enableHighAccuracy: true, timeout: 30000, maximumAge: 15000 };
  if (inDesktop() && isPhone()) {
    const geo = await import("@tauri-apps/plugin-geolocation");
    let perm = await geo.checkPermissions();
    if (perm.location !== "granted") perm = await geo.requestPermissions(["location"]);
    if (perm.location !== "granted") { onError("اسمح للتطبيق يستخدم الموقع (Location) من إعدادات الموبايل."); return () => undefined; }
    const id = await geo.watchPosition(opts, (pos, err) => {
      if (pos) onFix({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy ?? null });
      else if (err) onError("شغّل الـ Location في الموبايل.");
    });
    return () => { geo.clearWatch(id).catch(() => undefined); };
  }
  if (!navigator.geolocation || !window.isSecureContext) {
    onError("المكان مش متاح هنا: استخدم تطبيق الموبايل، أو افتح البرنامج على اتصال آمن (https).");
    return () => undefined;
  }
  const id = navigator.geolocation.watchPosition(
    (p) => onFix({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy ?? null }),
    () => onError("اسمح للبرنامج يستخدم الموقع."), opts);
  return () => navigator.geolocation.clearWatch(id);
}
