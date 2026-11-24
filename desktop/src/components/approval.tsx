// تأكيد مدير المبيعات on a survey or a quotation: send it to him, or (the manager) confirm it.
import { api } from "../api/client";
import { useAction } from "../lib/hooks";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Btn, Chip } from "./ui";

type Approvable = { id: string; branch_id: string; approval_status?: string };

export function ApprovalBar<T extends Approvable>({ kind, rec, onSaved }: { kind: "surveys" | "quotations"; rec: T; onSaved: (x: T) => void }) {
  const s = useSession();
  const toast = useToast();
  const { busy, run } = useAction(toast.err);
  const st = rec.approval_status ?? "approved";
  const canWrite = s.can(kind === "surveys" ? "surveys.write" : "quotes.write", rec.branch_id);
  const canApprove = s.can(kind === "surveys" ? "surveys.approve" : "quotes.approve", rec.branch_id);
  const post = (action: string, msg: string) => run(async () => {
    onSaved(await api.post<T>(`/${kind}/${rec.id}/${action}`));
    toast.ok(msg);
  });
  return (
    <>
      {st === "approved" && <Chip color="green">متأكدة من مدير المبيعات</Chip>}
      {st === "pending" && <Chip color="amber">مستنية تأكيد مدير المبيعات</Chip>}
      {st === "none" && <Chip>لسه ماتأكدتش</Chip>}
      {st === "none" && canWrite && !canApprove &&
        <Btn icon="send" busy={busy} onClick={() => post("request-approval", "اتبعتت لمدير المبيعات.")}>ابعت لمدير المبيعات للتأكيد</Btn>}
      {st !== "approved" && canApprove &&
        <Btn kind="success" icon="check" busy={busy} onClick={() => post("approve", "اتأكدت.")}>تأكيد</Btn>}
    </>
  );
}
