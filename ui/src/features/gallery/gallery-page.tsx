import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader } from "../../components/ui/card";
import { Pill } from "../../components/ui/pill";
import { Skeleton } from "../../components/ui/skeleton";
import { SourceDot, sourceName } from "../../components/ui/source-dot";
import { ThemeSwitcher } from "../../components/theme-switcher";
import { clampGlow, clampTextScale, GLOW_RANGE, TEXT_SCALE_RANGE, useDisplay } from "../../lib/display";
import { SOURCES } from "../../lib/sources";

// Dev only (decision 0342): router.tsx mounts this behind import.meta.env.DEV, so the production build
// carries neither the route's code nor this file. Swatches use literal classes because no inline style
// is allowed (decision 0301) and Tailwind cannot see class names built at run time.
const SWATCHES = [
  { name: "bgc", className: "bg-bg" },
  { name: "glass", className: "bg-glass" },
  { name: "bar", className: "bg-bar" },
  { name: "pop", className: "bg-pop" },
  { name: "chip", className: "bg-chip" },
  { name: "line", className: "bg-line" },
  { name: "line2", className: "bg-line2" },
  { name: "text", className: "bg-fg" },
  { name: "text2", className: "bg-muted" },
  { name: "text3", className: "bg-subtle" },
  { name: "ice", className: "bg-accent" },
  { name: "over", className: "bg-danger" },
] as const;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-3">
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Controls() {
  const { display, setDisplay } = useDisplay();
  return (
    <Card className="flex flex-col gap-3 p-4" aria-label="Display controls" role="group">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-muted">Theme</span>
        <ThemeSwitcher />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={display.highContrast}
            onChange={(event) => {
              setDisplay({ highContrast: event.target.checked });
            }}
          />
          High contrast
        </label>
        <div role="group" aria-label="Density" className="flex gap-1">
          {(["comfortable", "compact"] as const).map((density) => (
            <Button
              key={density}
              size="sm"
              variant={display.density === density ? "default" : "outline"}
              aria-pressed={display.density === density}
              onClick={() => {
                setDisplay({ density });
              }}
            >
              {density === "comfortable" ? "Comfortable" : "Compact"}
            </Button>
          ))}
        </div>
      </div>
      <label className="flex items-center gap-3">
        Glow {display.glow.toFixed(1)}
        <input
          type="range"
          min={GLOW_RANGE.min}
          max={GLOW_RANGE.max}
          step={GLOW_RANGE.step}
          value={display.glow}
          onChange={(event) => {
            setDisplay({ glow: clampGlow(event.target.valueAsNumber) });
          }}
        />
      </label>
      <label className="flex items-center gap-3">
        Text scale {display.textScale}%
        <input
          type="range"
          min={TEXT_SCALE_RANGE.min}
          max={TEXT_SCALE_RANGE.max}
          step={TEXT_SCALE_RANGE.step}
          value={display.textScale}
          onChange={(event) => {
            setDisplay({ textScale: clampTextScale(event.target.valueAsNumber) });
          }}
        />
      </label>
    </Card>
  );
}

export function GalleryPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-xl font-semibold">Gallery</h1>
      <Controls />

      <Section title="Tokens">
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {SWATCHES.map((swatch) => (
            <li key={swatch.name} className="flex items-center gap-2">
              <span className={`size-6 rounded-chip border border-line2 ${swatch.className}`} aria-hidden="true" />
              <span className="text-caption">{swatch.name}</span>
            </li>
          ))}
        </ul>
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {SOURCES.map((source) => (
            <li key={source.id} data-source={source.id} className="flex items-center gap-2">
              <SourceDot source={source.id} />
              <span className="text-(color:--cc-ink)">{sourceName(source.id)}</span>
            </li>
          ))}
        </ul>
        <p className="text-caption text-muted">
          Shape: widget 18, control 10, chip 8, pill 11, block 4. Type: Sora for headings, times, pills and badges.
        </p>
      </Section>

      <Section title="Priority pills">
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: 10 }, (_, index) => (
            <Pill key={index} priority={index + 1} />
          ))}
        </div>
      </Section>

      <Section title="Buttons and badges">
        <div className="flex flex-wrap items-center gap-2">
          <Button>Default</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button size="sm">Small</Button>
          <Button disabled>Disabled</Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge>Default</Badge>
          <Badge variant="outline">Outline</Badge>
          <Badge variant="accent">Now</Badge>
          <Badge variant="destructive">Overdue</Badge>
        </div>
      </Section>

      <Section title="Tabular figures">
        <p className="flex items-baseline gap-4">
          <span id="tnum-ones" className="tnum inline-block font-display text-lg">
            1111
          </span>
          <span id="tnum-zeros" className="tnum inline-block font-display text-lg">
            0000
          </span>
          <span className="text-caption text-muted">Equal widths with tnum on.</span>
        </p>
      </Section>

      <Section title="Glass cards">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SOURCES.map((source) => (
            <Card key={source.id} source={source.id}>
              <CardHeader>
                <div className="flex items-center gap-2 font-display text-lg font-semibold">
                  <SourceDot source={source.id} />
                  {sourceName(source.id)}
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="tnum font-display">9:30 AM</span>
                  <Pill priority={7} />
                </div>
                <Skeleton className="w-2/3" />
                <Skeleton className="w-1/2" />
              </CardContent>
            </Card>
          ))}
        </div>
      </Section>
    </div>
  );
}
