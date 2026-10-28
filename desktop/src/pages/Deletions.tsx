// جاري الحذف: everything waiting its 30 days, and what was deleted, cancelled or could not be deleted.
import { useState } from "react";
import { api, type S } from "../api/client";
import { useTitle, type PageProps } from "../lib/title";
import { useLoad } from "../lib/hooks";
import { dateTime } from "../lib/format";
import { Card, Chip, Table, Tabs } from "../components/ui";
import { PendingDelete } from "../components/actions";
import { useDeletions } from "../state/deletions";

type Deletion = S<"DeletionOut">;
const DONE: Record<string, [string, "green" | "gray" | "red"]> = {
  done: ["اتحذف", "green"], cancelled: ["اتلغى", "gray"], failed: ["ماتحذفش", "red"] };

export default function Deletions(_: PageProps) {
  useTitle("جاري الحذف");
  const [tab, setTab] = useState("pending");
  const pending = useDeletions();
  const old = useLoad(() => tab === "pending" ? Promise.resolve([] as Deletion[]) : api.get<Deletion[]>("/deletions", { status: tab }), [tab]);
  return (
    <div className="col">
      <p className="def-help">أي حاجة بتتحذف بتستنى ٣٠ يوم وعليها عداد، وبعدها بتتحذف نهائي. صاحب صلاحية «الحذف النهائي» يقدر يحذفها فورًا من العداد، واللي طلب الحذف أو صاحب الصلاحية يقدر يتراجع. حركات الفلوس مابتتحذفش، بتتعكس.</p>
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "pending", label: `مستني (${pending.length})` }, { id: "done", label: "اتحذف" },
        { id: "cancelled", label: "اتلغى" }, { id: "failed", label: "ماتحذفش" }]} />
      <Card flush>
        <Table rows={tab === "pending" ? pending : old.data} loading={tab !== "pending" && old.loading} empty="مفيش حاجة" columns={[
          { key: "l", label: "الحاجة", render: (d) => <b>{d.label}</b> },
          { key: "b", label: "طلب الحذف", render: (d) => d.requested_by_name || "—" },
          { key: "a", label: "اتطلب", render: (d) => <span className="num">{dateTime(d.requested_at)}</span> },
          tab === "pending"
            ? { key: "c", label: "الحذف النهائي", render: (d) => <PendingDelete req={d} /> }
            : { key: "s", label: "الحالة", render: (d) => <span><Chip color={DONE[d.status]?.[1]}>{DONE[d.status]?.[0] ?? d.status}</Chip>
                {" "}<span className="num small muted">{dateTime(d.finished_at)}</span>{d.status === "failed" && d.note && <span className="small muted"> · {d.note}</span>}</span> },
        ]} />
      </Card>
    </div>
  );
}
