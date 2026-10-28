import { useState, type MouseEvent } from "react";
import { api, errorText } from "../api/client";
import { date, dateTime } from "../lib/format";
import { countdown, pendingFor, reloadDeletions, useDeletions, useNow, type Deletion } from "../state/deletions";
import { useToast } from "../state/toast";
import { Btn, Confirm, Modal } from "./ui";

type DeleteResult = { result: "scheduled" | "deleted" | "deactivated" | string; due_at?: string | null };

const WAIT = "هيتعلّم «جاري الحذف» ويتحذف نهائي بعد ٣٠ يوم، وتقدر تتراجع قبلها. صاحب صلاحية الحذف النهائي يقدر يحذفه فورًا من العداد.";

/** Delete with a confirmation. It waits 30 days with a countdown on it; the permanent delete permission erases it
 * at once from the countdown. `onDone` runs once it is really deleted. */
export function DeleteBtn({ path, what, onDone, small = true, label = "حذف", note }:
  { path: string; what: string; onDone: (r: DeleteResult) => void; small?: boolean; label?: string; note?: string }) {
  const pending = pendingFor(useDeletions(), path);
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  if (pending) return <PendingDelete req={pending} what={what} small={small} onDone={onDone} />;
  const yes = async () => {
    setBusy(true);
    try {
      const r = await api.del<DeleteResult>(path);
      await reloadDeletions();
      setAsk(false);
      if (r.result === "scheduled") toast.ok(`اتطلب حذف ${what}: هيتحذف نهائي يوم ${date(r.due_at)}.`);
      else { toast.ok(`اتمسح ${what}.`); onDone(r); }
    } catch (e) {
      toast.err(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Btn small={small} kind="danger" icon="trash" onClick={(e: MouseEvent) => { e.stopPropagation(); setAsk(true); }}>{label}</Btn>
      {ask && (
        <span onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
          <Confirm danger title={`حذف ${what}`} yes="أيوه، احذف" busy={busy} onYes={yes} onClose={() => setAsk(false)}
            text={`${note ? note + " " : ""}${WAIT}`} />
        </span>
      )}
    </>
  );
}

/** «جاري الحذف» with the countdown; a click shows who asked, and «احذف نهائي دلوقتي» / «تراجع عن الحذف». */
export function PendingDelete({ req, what, small = true, onDone }:
  { req: Deletion; what?: string; small?: boolean; onDone?: (r: DeleteResult) => void }) {
  const now = useNow();
  const [open, setOpen] = useState(false);
  return (
    <span onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
      <button type="button" className={"btn danger-soft" + (small ? " sm" : "")} title="جاري الحذف" onClick={() => setOpen(true)}>
        ⏳ جاري الحذف <Left dueAt={req.due_at} now={now} />
      </button>
      {open && <PendingDeleteDialog req={req} what={what} onClose={() => setOpen(false)} onDone={onDone} />}
    </span>
  );
}

function Left({ dueAt, now }: { dueAt: string; now: number }) {
  const { days, clock } = countdown(dueAt, now);
  return <span><span className="num">{days}</span> يوم و<span className="num" dir="ltr">{clock}</span></span>;
}

export function PendingDeleteDialog({ req, what, onClose, onDone }:
  { req: Deletion; what?: string; onClose: () => void; onDone?: (r: DeleteResult) => void }) {
  const now = useNow();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [sure, setSure] = useState(false);
  const act = (kind: "now" | "cancel") => async () => {
    setBusy(true);
    try {
      const out = await api.post<Deletion>(`/deletions/${req.id}/${kind}`);
      await reloadDeletions();
      onClose();
      if (kind === "now") { toast.ok(`اتحذف ${what ?? req.label} نهائي.`); onDone?.({ result: out.note || "deleted" }); }
      else toast.ok(`اتلغى حذف ${what ?? req.label}.`);
    } catch (e) {
      toast.err(errorText(e));
      await reloadDeletions();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={`جاري حذف ${what ?? req.label}`} onClose={onClose} footer={<>
      {req.can_delete_now && (sure
        ? <Btn kind="danger" busy={busy} onClick={act("now")}>متأكد: احذف نهائي</Btn>
        : <Btn kind="danger" icon="trash" onClick={() => setSure(true)}>احذف نهائي دلوقتي</Btn>)}
      {req.can_cancel && <Btn busy={busy} onClick={act("cancel")}>تراجع عن الحذف</Btn>}
      <Btn onClick={onClose}>رجوع</Btn></>}>
      <div className="col">
        <div className="notice warn">باقي على الحذف النهائي <b><Left dueAt={req.due_at} now={now} /></b> (يوم <span className="num">{date(req.due_at)}</span>).</div>
        <div className="small">طلب الحذف: <b>{req.requested_by_name || "—"}</b> · <span className="num">{dateTime(req.requested_at)}</span></div>
        {sure && <div className="notice danger small">الحذف النهائي مالوش رجوع. أي شغل قديم بيفضل محتفظ بنسخته، والشغل المفتوح اللي مستخدمه هيوصله إشعار يغيّره.</div>}
        {!req.can_delete_now && !req.can_cancel && <div className="muted small">التراجع للي طلب الحذف أو لصاحب صلاحية الحذف النهائي.</div>}
      </div>
    </Modal>
  );
}
