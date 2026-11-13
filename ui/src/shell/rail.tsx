import { Link } from "@tanstack/react-router";
import {
  Crosshair,
  Eye,
  EyeOff,
  History,
  LayoutDashboard,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { useId } from "react";
import { useDisplaySettings } from "../features/display/display-settings";
import { cn } from "../lib/utils";

export interface RailLink {
  readonly to: "/dashboard" | "/chat" | "/history" | "/focus" | "/settings";
  readonly label: string;
  readonly icon: LucideIcon;
}

/** Top group, in order. There is no "Design rules" item: that page is a prototype reference and does not ship (decision 0394). */
export const TOP_LINKS: readonly RailLink[] = [
  { to: "/dashboard", label: "Today", icon: LayoutDashboard },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/history", label: "History", icon: History },
  { to: "/focus", label: "Focus", icon: Crosshair },
];

export const SETTINGS_LINK: RailLink = { to: "/settings", label: "Settings", icon: Settings };

const ITEM =
  "flex min-h-8 w-full items-center gap-3 rounded-control px-3 text-left font-medium text-fg hover:bg-chip";
const ACTIVE = "bg-chip";

/** The label is real text, so the accessible name is the visible name. Collapsed, the text is visually hidden and
 *  still the name: never an aria-label that differs from it (axe label-content-name-mismatch). */
function Label({ collapsed, children }: { collapsed: boolean; children: string }) {
  // Below the md breakpoint the rail is always icon width (decision 0397): the text is hidden the same way, by CSS.
  return <span className={cn(collapsed ? "sr-only" : "max-md:sr-only")}>{children}</span>;
}

function RailItem({ link, collapsed }: { link: RailLink; collapsed: boolean }) {
  const Icon = link.icon;
  return (
    <li>
      <Link
        to={link.to}
        className={ITEM}
        activeProps={{ "aria-current": "page", className: cn(ITEM, ACTIVE) }}
        title={collapsed ? link.label : undefined}
      >
        <Icon size={18} aria-hidden="true" className="flex-none" />
        <Label collapsed={collapsed}>{link.label}</Label>
      </Link>
    </li>
  );
}

export interface RailProps {
  readonly collapsed: boolean;
  readonly onToggle: () => void;
}

export function Rail({ collapsed, onToggle }: RailProps) {
  const { settings, update } = useDisplaySettings();
  const hintId = useId();
  const on = settings.privacy_mode;
  const PrivacyIcon = on ? EyeOff : Eye;
  const Toggle = collapsed ? PanelLeftOpen : PanelLeftClose;
  return (
    <nav
      aria-label="Main"
      data-testid="rail"
      data-collapsed={collapsed ? "true" : "false"}
      className={cn(
        "flex flex-none flex-col justify-between gap-4 border-r border-line p-2",
        collapsed ? "w-14" : "w-44 max-md:w-14",
      )}
    >
      <div className="flex flex-col gap-2">
        {/* Hidden below md, where the rail is icon width whatever the stored preference says (decision 0397). */}
        <button type="button" aria-expanded={!collapsed} className={cn(ITEM, "max-md:hidden")} onClick={onToggle}>
          <Toggle size={18} aria-hidden="true" className="flex-none" />
          <Label collapsed={collapsed}>Menu</Label>
        </button>
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {TOP_LINKS.map((link) => (
            <RailItem key={link.to} link={link} collapsed={collapsed} />
          ))}
        </ul>
      </div>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        <li>
          <button
            type="button"
            aria-pressed={on}
            aria-describedby={hintId}
            className={cn(ITEM, on && ACTIVE)}
            title={collapsed ? "Privacy" : undefined}
            onClick={() => {
              update({ privacy_mode: !on });
            }}
          >
            <PrivacyIcon size={18} aria-hidden="true" className="flex-none" />
            <Label collapsed={collapsed}>Privacy</Label>
          </button>
          <span id={hintId} className="sr-only">
            Blurs titles, notes, places and names on screen. A visual mask only: the text is still there and nothing is
            hidden from other software.
          </span>
        </li>
        <RailItem link={SETTINGS_LINK} collapsed={collapsed} />
      </ul>
    </nav>
  );
}
