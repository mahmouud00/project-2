// CI only: gives every build its own version, <major>.<minor>.<build number> from VERSION (0.1.0 -> 0.1.57), and writes
// it everywhere a program reports its version (server VERSION, desktop package.json, tauri.conf.json, Cargo.toml).
// The programs compare these numbers to offer an update, so two builds must never share one.
// usage: node tools/release/stamp_version.mjs <build number>
import { readFileSync, writeFileSync } from "node:fs";

const build = Number(process.argv[2]);
if (!Number.isInteger(build) || build < 1) throw new Error("build number required");
const [major, minor] = readFileSync("VERSION", "utf8").trim().split(".");
const v = `${Number(major)}.${Number(minor)}.${build}`;

writeFileSync("VERSION", v + "\n");
for (const f of ["desktop/package.json", "desktop/src-tauri/tauri.conf.json"]) {
  const j = JSON.parse(readFileSync(f, "utf8"));
  j.version = v;
  writeFileSync(f, JSON.stringify(j, null, 2) + "\n");
}
const cargo = "desktop/src-tauri/Cargo.toml";
writeFileSync(cargo, readFileSync(cargo, "utf8").replace(/^version = ".*"$/m, `version = "${v}"`));
console.log(v);
