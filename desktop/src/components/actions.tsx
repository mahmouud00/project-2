import { useState, type MouseEvent } from "react";
import { api, errorText } from "../api/client";
import { useToast } from "../state/toast";
import { Btn, Confirm } from "./ui";

type DeleteResult = { result: "deleted" | "deactivated" | string };

/** Delete with a confirmation. Records with history are stopped instead of erased; the server decides and says so. */
export function DeleteBtn({ path, what, onDone, small = true, label = "حذف", note }:
  { path: string; what: string; onDone: (r: DeleteResult) => void; small?: boolean; label?: string; note?: string }) {
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const yes = async () => {
    setBusy(true);
    try {
      const r = await api.del<DeleteResult>(path);
      toast.ok(r.result === "deactivated" ? `${what}: عليه حركات قديمة، فاتوقّف واختفى من القوايم بدل ما يتمسح.` : `اتمسح ${what}.`);
      setAsk(false);
      onDone(r);
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
            text={note ?? `متأكد إنك عايز تحذف ${what}؟ لو عليه حركات قديمة هيتوقّف بس ومش هيظهر في القوايم.`} />
        </span>
      )}
    </>
  );
}
