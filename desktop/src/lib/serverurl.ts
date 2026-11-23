/** What the user typed → the server's address. A factory server on the network (an IP, «localhost», a PC name) is
 *  http on port 8000 unless a port is given; a cloud server (a domain like app.wintag.tech, or anything typed with
 *  https://) is https on its normal port. */
export function normalizeServer(input: string): string {
  let s = input.trim().replace(/\/+$/, "");
  const scheme = s.match(/^(https?):\/\//i)?.[1]?.toLowerCase();
  const rest = s.replace(/^https?:\/\//i, "");
  const host = rest.split("/")[0];
  const hasPort = /:\d+$/.test(host);
  const name = host.replace(/:\d+$/, "");
  const local = /^\d{1,3}(\.\d{1,3}){3}$/.test(name) || name === "localhost" || !name.includes(".") || /\.local$/i.test(name);
  if (scheme === "https") return s;
  if (!scheme && !local) return "https://" + rest;
  s = "http://" + rest;
  if (!hasPort && local) s = s.replace(host, host + ":8000");
  return s;
}
