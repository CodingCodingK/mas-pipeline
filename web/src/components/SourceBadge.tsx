import type { SourceKind } from "@/api/types";

const CLASS_MAP: Record<SourceKind, string> = {
  global: "bg-slate-100 text-slate-700",
  "project-only": "bg-emerald-100 text-emerald-800",
  "project-override": "bg-amber-100 text-amber-800",
  // `project` is the shape emitted by the effective-read endpoint, rendered same as override.
  project: "bg-amber-100 text-amber-800",
};

export default function SourceBadge({ source }: { source: SourceKind }) {
  const cls = CLASS_MAP[source] ?? "bg-slate-100 text-slate-700";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {source}
    </span>
  );
}
