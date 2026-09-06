import { ReactNode } from "react";
import { motion } from "framer-motion";

/**
 * The single definition of what a page looks like.
 *
 * Every view renders through this, so heading hierarchy, page width, spacing and
 * the entry animation are declared once instead of being re-invented per screen.
 * Panels keep using GlassCard, so the whole app reads as one surface treatment:
 * frosted cards on the ambient gradient, teal for money/positive, violet for
 * projections, amber and rose for warnings.
 */
export default function PageShell({
  eyebrow,
  title,
  description,
  children,
}: {
  /** Short category label above the title. */
  eyebrow: string;
  title: string;
  /** One line explaining what the page is for. */
  description: string;
  children: ReactNode;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className="mx-auto max-w-7xl px-4 pb-16 pt-6 md:px-6"
    >
      <header className="mb-6">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-teal-accent/80">
          {eyebrow}
        </p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-100 md:text-3xl">
          {title}
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm text-slate-400">{description}</p>
      </header>

      {/* Shared 3-column grid. Panels opt into width with lg:col-span-*. */}
      <div className="grid gap-4 lg:grid-cols-3">{children}</div>
    </motion.section>
  );
}

/** Full-width row inside a PageShell grid. */
export function Row({ children }: { children: ReactNode }) {
  return <div className="lg:col-span-3">{children}</div>;
}

/** Two-thirds-width cell inside a PageShell grid. */
export function Wide({ children }: { children: ReactNode }) {
  return <div className="lg:col-span-2">{children}</div>;
}
