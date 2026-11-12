import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Star } from "@/components/ui/Star";
import { formatNumber, formatUsd, regionLabel } from "@/lib/format";
import type { CampaignCard as Card } from "@/types/api";
const recipientImages: Record<string, string> = {
  bilal: "/images/recipients/bilal.png",
  ruqaiyya: "/images/recipients/ruqaiyya.png",
  wanjiru: "/images/recipients/wanjiru.png",
  chidi: "/images/recipients/chidi.png",
  hanna: "/images/recipients/hanna.png",
  siti: "/images/recipients/siti.png",
  imran: "/images/recipients/imran.png",
  fatima: "/images/recipients/fatima.png"
};

/** One campaign in a grid. `amount` (cents) is carried to the detail page so a giving-calculator amount survives the click. */
export function CampaignCard({ campaign: c, amount }: { campaign: Card; amount?: number | null }) {
  const href = `/campaigns/${c.slug}${amount ? `?amount=${amount}` : ""}`;
  const recipientKey = c.recipient.name.trim().toLowerCase();
const coverUrl = recipientImages[recipientKey] ?? c.cover_url;
  return (
    <article className="group flex h-full flex-col overflow-hidden rounded-2xl bg-paper ring-1 ring-line transition-shadow hover:shadow-[var(--shadow-lift)]">
      <Link href={href} className="block" aria-label={`${c.title}, ${c.recipient.name}`}>
        {coverUrl ? (
  <img
    src={coverUrl}
    alt={`Illustrative image for ${c.recipient.name}`}
    loading="lazy"
    className="h-44 w-full object-cover object-[center_20%]"
  />
) : (
  <div className="pattern-stars-dark flex h-44 items-center justify-center bg-lapis-50" aria-hidden>
    <Star className="size-14 text-saffron-400" />
  </div>
)}
      </Link>
      <div className="flex flex-1 flex-col p-5">
        <p className="text-sm font-medium text-ink-soft">
          {c.recipient.name}
          {c.recipient.business_type ? ` · ${c.recipient.business_type}` : ""} · {regionLabel(c.recipient.region_country, c.recipient.region_admin1)}
        </p>
        <h3 className="mt-1 text-xl font-semibold">
          <Link href={href} className="hover:text-lapis-700">
            {c.title}
          </Link>
        </h3>
        <p className="mt-2 line-clamp-3 text-ink-soft">{c.excerpt}</p>
        <div className="mt-auto pt-5">
          <ProgressBar percent={c.percent_funded} label={`${c.title} funding progress`} />
          <div className="mt-2 flex items-baseline justify-between gap-3 text-base">
            <span>
              <strong className="font-semibold">{formatUsd(c.raised_cents)}</strong>
              <span className="text-ink-soft"> of {formatUsd(c.goal_cents)}</span>
            </span>
            {c.status === "funded" ? (
              <Badge tone="ok">Fully funded</Badge>
            ) : (
              <span className="text-sm text-ink-soft">
                {formatNumber(c.donor_count)} {c.donor_count === 1 ? "gift" : "gifts"}
              </span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
