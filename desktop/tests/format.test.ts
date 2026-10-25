import { fromMm, toMm, sumMoney, clean, mulMoney, subDec } from "../src/lib/format.ts";
const cases: [string, string][] = [["1800.00","180"],["1796.5","179.65"],["5","0.5"],["0","0"],["0.4","0.04"],["-12","-1.2"],["1000","100"]];
for (const [mm, cm] of cases) { const r = fromMm(mm); if (r !== cm) throw new Error(`fromMm ${mm} -> ${r} != ${cm}`); }
const back: [string, string|null][] = [["180","1800"],["179.65","1796.5"],["0.5","5"],["١٨٠","1800"],["12,5","125"],["abc",null],["",null]];
for (const [cm, mm] of back) { const r = toMm(cm); if (r !== mm) throw new Error(`toMm ${cm} -> ${r} != ${mm}`); }
if (toMm("1796.5","mm") !== "1796.5") throw new Error("mm");
if (sumMoney(["0.10","0.20","1000.05"]) !== "1000.35") throw new Error("sum " + sumMoney(["0.10","0.20","1000.05"]));
if (sumMoney(["-5.5","2"]) !== "-3.50") throw new Error("neg sum");
if (clean("12.500") !== "12.5") throw new Error("clean");
for (const [a, b, r] of [["60", "120", "7200.00"], ["2.5", "0.333", "0.83"], ["3", "1.005", "3.02"], ["0.1", "0.2", "0.02"], ["1", "", "0.00"]]) {
  if (mulMoney(a, b) !== r) throw new Error(`mul ${a}*${b} -> ${mulMoney(a, b)} != ${r}`);
}
for (const [a, b, r] of [["1800.00", "1200.00", "600"], ["1800", "1795.5", "4.5"], ["0.3", "0.1", "0.2"], ["100", "250", "-150"]]) {
  if (subDec(a, b) !== r) throw new Error(`sub ${a}-${b} -> ${subDec(a, b)} != ${r}`);
}
console.log("format ok");
