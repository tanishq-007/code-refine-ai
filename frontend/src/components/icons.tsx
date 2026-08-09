import type { SVGProps } from 'react'

/* Hand-drawn 16px stroke icons (lucide-style): consistent 1.5px stroke,
   currentColor, round caps — so they inherit text color everywhere. */

function Base({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden {...props}>
      {children}
    </svg>
  )
}

export const HomeIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /><path d="M10 21v-6h4v6" /></Base>
)

export const GridIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><rect x="3" y="3" width="7.5" height="7.5" rx="1.5" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" /></Base>
)

export const ListIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><path d="M9 6h12" /><path d="M9 12h12" /><path d="M9 18h12" /><circle cx="4.5" cy="6" r="1" fill="currentColor" /><circle cx="4.5" cy="12" r="1" fill="currentColor" /><circle cx="4.5" cy="18" r="1" fill="currentColor" /></Base>
)

export const MapIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><path d="M9 4 3 6.5v13L9 17l6 2.5 6-2.5v-13L15 6.5 9 4Z" /><path d="M9 4v13" /><path d="M15 6.5v13" /></Base>
)

export const WrenchIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><path d="M14.5 6.5a4.5 4.5 0 0 0 5.8 5.6L14 18.4a2.1 2.1 0 0 1-3-3l6.3-6.3a4.5 4.5 0 0 0-5.6-5.8l2.9 2.9-1.2 3-3 1.2-2.9-2.9" /></Base>
)

export const ChevronDownIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><path d="m6 9 6 6 6-6" /></Base>
)

export const PanelLeftIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9.5 4v16" /></Base>
)

export const PencilIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><path d="M17 3.5 20.5 7 8.5 19l-4.5 1 1-4.5L17 3.5Z" /><path d="m14.5 6 3.5 3.5" /></Base>
)

export const PlayIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><path d="M7 4.5v15l12-7.5L7 4.5Z" /></Base>
)

export const SunIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M18.7 5.3l-1.8 1.8M7.1 16.9l-1.8 1.8" /></Base>
)

export const MoonIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base {...p}><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z" /></Base>
)

export const LogoIcon = (p: SVGProps<SVGSVGElement>) => (
  <Base strokeWidth="2" {...p}><path d="m8 6-5 6 5 6" /><path d="m16 6 5 6-5 6" /><path d="M13.5 4.5 10.5 19.5" /></Base>
)
