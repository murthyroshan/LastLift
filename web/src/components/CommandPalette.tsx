import { Command } from "cmdk";
import { useEffect, useState } from "react";
import { getState, getStations } from "../api";
import { href } from "../router";
import { S } from "../strings.en";
import { I } from "./icons";

type Action = { id: string; label: string; run: () => void };

/** ⌘K / Ctrl+K: jump to any station, lift, page or action. cmdk gives the combobox and listbox semantics. */
export function CommandPalette({ open, setOpen, actions }: { open: boolean; setOpen: (v: boolean) => void; actions: Action[] }) {
  const [stations, setStations] = useState<{ id: string; name: string; single: number; lost: number }[]>([]);
  const [lifts, setLifts] = useState<{ facility_id: string; name: string; station_id: string; tier_label: string }[]>([]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(!open); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, setOpen]);

  useEffect(() => {
    if (!open || stations.length) return;
    getStations().then(setStations).catch(() => {});
    getState().then((s) => setLifts(s.priority.data.ranked)).catch(() => {});
  }, [open, stations.length]);

  const go = (path: string) => { window.location.hash = href(path).slice(1); setOpen(false); };
  const pages: [string, string, keyof typeof I][] = [
    ["/", S.nav.home, "story"], ["/console", S.tabs.live, "command"], ["/approvals", S.tabs.agents, "ops"],
    ["/network", S.tabs.network, "network"], ["/history", S.tabs.history, "story"], ["/repairs", S.tabs.priorities, "repairs"],
    ["/sandbox", S.tabs.whatif, "lift"], ["/about", S.tabs.how, "about"], ["/atlas", S.tabs.cities, "network"]];

  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label={S.palette.label} className="cmdk" overlayClassName="cmdk-overlay">
      <div className="cmdk-input-row">
        <I.search />
        <Command.Input placeholder={S.palette.placeholder} />
        <kbd>Esc</kbd>
      </div>
      <Command.List>
        <Command.Empty>{S.palette.empty}</Command.Empty>
        <Command.Group heading={S.palette.pages}>
          {pages.map(([p, label, icon]) => {
            const Icon = I[icon];
            return <Command.Item key={p} value={`page ${label}`} onSelect={() => go(p)}><Icon /> {label}</Command.Item>;
          })}
        </Command.Group>
        <Command.Group heading={S.palette.actions}>
          {actions.map((a) => (
            <Command.Item key={a.id} value={`action ${a.label}`} onSelect={() => { a.run(); setOpen(false); }}>
              <I.agent /> {a.label}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading={S.palette.stations}>
          {stations.map((s) => (
            <Command.Item key={s.id} value={`station ${s.name}`} onSelect={() => go(`/station/${s.id}`)}>
              <I.station /> <span className="cmdk-main">{s.name}</span>
              {s.lost > 0 && <span className="pill" data-k="0">✕ {s.lost}</span>}
              {s.single > 0 && <span className="pill" data-k="1">◆ {s.single}</span>}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading={S.palette.lifts}>
          {lifts.map((l, i) => (
            <Command.Item key={`${l.facility_id}-${i}`} value={`lift ${l.facility_id} ${l.station_id} ${l.name}`} onSelect={() => go(`/station/${l.station_id}`)}>
              <I.lift /> <span className="cmdk-main"><span className="mono">{l.facility_id}</span> {l.name}</span>
              <span className="cmdk-meta">{l.tier_label}</span>
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
