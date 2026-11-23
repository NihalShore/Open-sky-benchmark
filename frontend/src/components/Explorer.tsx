import { Search, Crosshair, ChevronRight, CircleDot } from "lucide-react";
import type { Target } from "../data/catalog";
import { useMemo, useState } from "react";

const CLASS_COLOR: Record<string, string> = {
  YSO: "#ffb224",
  AGN: "#b794ff",
  Blazar: "#ff7ab8",
  Mira: "#ff8a5c",
  SN: "#ff5c5c",
  EB: "#46d5e8",
};

export function TargetExplorer({
  targets, activeId, onSelect, filterMission,
}: {
  targets: Target[];
  activeId: string;
  onSelect: (id: string) => void;
  filterMission: string;
}) {
  const [q, setQ] = useState("");
  const [classF, setClassF] = useState<string>("All");
  const classes = useMemo(() => ["All", ...Array.from(new Set(targets.map(t => t.varClass)))], [targets]);
  const list = targets.filter(t => {
    const okQ = q.trim() === "" || (t.name + t.altName + t.varClassLabel).toLowerCase().includes(q.toLowerCase());
    const okC = classF === "All" || t.varClass === classF;
    const okM = filterMission === "All" || t.epochs.some(e => e.mission === filterMission);
    return okQ && okC && okM;
  });

  return (
    <div className="flex h-full flex-col">
      <div className="p-3 pb-2">
        <div className="flex items-center gap-2 rounded-md border border-[#24334f] bg-[#060b14] px-2.5 py-2 focus-within:border-[#ffb224]/50">
          <Search size={14} className="shrink-0 text-[#7d8fb0]" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, class, region…"
            className="w-full bg-transparent text-[12.5px] text-[#dbe4f3] placeholder:text-[#5a6b8c] focus:outline-none" />
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {classes.map(c => (
            <button key={c} onClick={() => setClassF(c)}
              className={`rounded px-2 py-1 font-mono2 text-[10px] tracking-wide transition ${classF === c ? "bg-[#ffb224] text-black font-semibold" : "border border-[#24334f] text-[#9fb0cc] hover:border-[#ffb224]/40 hover:text-white"}`}>
              {c}
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between px-3 py-1.5">
        <span className="font-mono2 text-[10px] tracking-[0.14em] text-[#5a6b8c]">CATALOG · {list.length} TARGETS</span>
        <span className="font-mono2 text-[10px] text-[#5a6b8c]">SIM-PREVIEW</span>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {list.map(t => {
          const active = t.id === activeId;
          const color = CLASS_COLOR[t.varClass] ?? "#7d8fb0";
          return (
            <button key={t.id} onClick={() => onSelect(t.id)}
              className={`mb-1 w-full rounded-lg border px-2.5 py-2.5 text-left transition ${active ? "border-[#ffb224]/55 bg-[#ffb224]/08" : "border-transparent hover:border-[#24334f] hover:bg-[#0a111d]"}`}>
              <div className="flex items-start gap-2">
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-display text-[13px] font-semibold text-white">{t.name}</span>
                    <span className="ml-auto shrink-0 font-mono2 text-[9px] text-[#5a6b8c]">{t.priority}</span>
                  </div>
                  <div className="mt-0.5 truncate font-mono2 text-[10px] text-[#7d8fb0]">{t.altName}</div>
                  <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 font-mono2 text-[10px] text-[#9fb0cc]">
                    <span style={{ color }}>{t.varClassLabel}</span>
                    <span>·</span>
                    <span>{t.epochs.length} epochs</span>
                  </div>
                </div>
                {active && <ChevronRight size={14} className="mt-1 shrink-0 text-[#ffb224]" />}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function TimelineStrip({
  target, epochAId, epochBId, onPick, slot, cursorMjd,
}: {
  target: Target;
  epochAId: string;
  epochBId: string;
  onPick: (id: string, slot: "A" | "B") => void;
  slot: "A" | "B";
  cursorMjd: number | null;
}) {
  const mjds = target.epochs.map(e => e.mjd);
  const min = Math.min(...mjds) - 20;
  const max = Math.max(...mjds) + 20;
  const x = (m: number) => ((m - min) / (max - min)) * 100;

  return (
    <div className="space-y-1.5">
      <div className="relative h-14 rounded-md border border-[#1b2740] bg-[#060b14] px-2">
        <div className="absolute inset-x-2 top-[22px] h-px bg-[#24334f]" />
        <div className="relative h-full">
          {target.epochs.map(e => {
            const isA = e.id === epochAId;
            const isB = e.id === epochBId;
            return (
              <button key={e.id} type="button" onClick={() => onPick(e.id, slot)}
                className="group absolute -translate-x-1/2 pt-0.5" style={{ left: `${x(e.mjd)}%` }}>
                <span className={`mx-auto block h-2 w-2 rotate-45 border transition ${isA ? "border-[#ffb224] bg-[#ffb224]" : isB ? "border-[#46d5e8] bg-[#46d5e8]" : "border-[#7d8fb0] bg-[#0a111d] group-hover:border-white"}`} />
                <span className={`mt-1 block whitespace-nowrap rounded border px-1.5 py-0.5 font-mono2 text-[9px] ${isA ? "border-[#ffb224]/50 bg-[#ffb224]/10 text-[#ffb224]" : isB ? "border-[#46d5e8]/50 bg-[#46d5e8]/10 text-[#7de8f5]" : "border-[#24334f] bg-[#060b14]/80 text-[#7d8fb0]"}`}>
                  {e.date.slice(2)} · {e.mission === "SPHEREx" ? "SPX" : "NEO"} {e.mag.toFixed(1)}
                </span>
              </button>
            );
          })}
        </div>
        {cursorMjd != null && (
          <div className="absolute top-[22px] h-2 w-px bg-white/40" style={{ left: `${x(cursorMjd)}%` }} />
        )}
      </div>
      <div className="flex items-center gap-3 font-mono2 text-[10px] text-[#7d8fb0]">
        <span className="flex items-center gap-1"><i className="inline-block h-2 w-2 rotate-45 border border-[#ffb224] bg-[#ffb224]" /> Epoch A</span>
        <span className="flex items-center gap-1"><i className="inline-block h-2 w-2 rotate-45 border border-[#46d5e8] bg-[#46d5e8]" /> Epoch B</span>
      </div>
    </div>
  );
}
