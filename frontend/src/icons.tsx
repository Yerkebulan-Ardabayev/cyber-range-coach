import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function IconBase({ children, ...props }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  )
}

export const CompassIcon = (props: IconProps) => <IconBase {...props}><circle cx="12" cy="12" r="9" /><path d="m15.6 8.4-2.1 5.1-5.1 2.1 2.1-5.1 5.1-2.1Z" /></IconBase>
export const BookIcon = (props: IconProps) => <IconBase {...props}><path d="M4 5.2A2.2 2.2 0 0 1 6.2 3H11v16H6.2A2.2 2.2 0 0 0 4 21V5.2Z" /><path d="M20 5.2A2.2 2.2 0 0 0 17.8 3H13v16h4.8A2.2 2.2 0 0 1 20 21V5.2Z" /></IconBase>
export const TerminalIcon = (props: IconProps) => <IconBase {...props}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3M13 15h4" /></IconBase>
export const TargetIcon = (props: IconProps) => <IconBase {...props}><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" /><path d="M12 2v3M22 12h-3M12 22v-3M2 12h3" /></IconBase>
export const EvidenceIcon = (props: IconProps) => <IconBase {...props}><path d="M7 3h10l3 3v15H4V3h3Z" /><path d="M8 10h8M8 14h8M8 18h5M14 3v4h6" /></IconBase>
export const RepeatIcon = (props: IconProps) => <IconBase {...props}><path d="M20 7h-9a5 5 0 0 0-5 5v1M4 17h9a5 5 0 0 0 5-5v-1" /><path d="m16 4 4 3-4 3M8 14l-4 3 4 3" /></IconBase>
export const NoteIcon = (props: IconProps) => <IconBase {...props}><path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5" /></IconBase>
export const StudioIcon = (props: IconProps) => <IconBase {...props}><path d="m12 3 1.4 4.1L18 8.5l-4.6 1.4L12 14l-1.4-4.1L6 8.5l4.6-1.4L12 3Z" /><path d="m18.5 14 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" /><path d="M4 14v7h9" /></IconBase>
export const SettingsIcon = (props: IconProps) => <IconBase {...props}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></IconBase>
export const MenuIcon = (props: IconProps) => <IconBase {...props}><path d="M4 7h16M4 12h16M4 17h16" /></IconBase>
export const ArrowIcon = (props: IconProps) => <IconBase {...props}><path d="M5 12h14M14 7l5 5-5 5" /></IconBase>
export const CheckIcon = (props: IconProps) => <IconBase {...props}><path d="m5 12 4 4L19 6" /></IconBase>
export const CloseIcon = (props: IconProps) => <IconBase {...props}><path d="M6 6l12 12M18 6 6 18" /></IconBase>
