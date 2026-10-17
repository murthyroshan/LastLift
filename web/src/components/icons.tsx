import type { SVGProps } from "react";

/** A small stroke icon set (24 px grid, 1.75 stroke). Always decorative: the visible label names the control. */
const base = (props: SVGProps<SVGSVGElement>) => ({
  width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.75,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, focusable: false, ...props,
});

export const I = {
  story: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M3 20l5-9 4 6 3-4 6 7z" /><circle cx="17" cy="6" r="2.5" /></svg>,
  command: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><circle cx="12" cy="12" r="9" /><path d="M12 3v4M12 17v4M3 12h4M17 12h4" /><circle cx="12" cy="12" r="2.5" /></svg>,
  network: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2" /><circle cx="12" cy="10" r="2" /><path d="M6.6 7.2l3.8 1.9M17.4 7.2l-3.8 1.9M12 12v4" /></svg>,
  repairs: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M14.7 6.3a4 4 0 0 0 5 5L21 13l-8 8-3-3 8-8-1.3-1.3a4 4 0 0 1-5-5" /><path d="M3 21l5-5" /></svg>,
  ops: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M3 12h4l3-8 4 16 3-8h4" /></svg>,
  about: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></svg>,
  agent: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M12 3l1.8 4.7L18.5 9l-4.7 1.8L12 15.5l-1.8-4.7L5.5 9l4.7-1.3z" /><path d="M18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z" /></svg>,
  ear: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M6 9a6 6 0 1 1 12 0c0 3-2 4-3 5.5S13.5 19 11 19a3 3 0 0 1-3-3" /><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-1.5 2-2.5 3" /></svg>,
  live: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><circle cx="12" cy="12" r="2" /><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14" /></svg>,
  search: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>,
  lift: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M12 6l3 3H9zM12 18l-3-3h6z" /></svg>,
  station: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M4 20h16M6 20V9l6-5 6 5v11" /><path d="M10 20v-5h4v5" /></svg>,
  arrow: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>,
  alert: (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4M12 17v.5" /></svg>,
};
