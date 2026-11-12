import type { Metadata } from "next";
import { SiteGuide } from "@/components/about/SiteGuide";
import { GivingCalculator } from "@/components/about/GivingCalculator";
import { LinkButton } from "@/components/ui/Button";
import { Star } from "@/components/ui/Star";

export const metadata: Metadata = {
  title: "About SadQah",
  description: "SadQah comes from the Arabic word صدقة (ṣadaqah): sincere, voluntary giving. Learn what it means and give 1% to 5% of your yearly income, or any amount you choose.",
};

const KINDRED = [
  { word: "Tzedakah", lang: "Hebrew", gloss: "giving as justice" },
  { word: "Dāna", lang: "Sanskrit and Pali", gloss: "the practice of generosity" },
  { word: "Ubuntu", lang: "Zulu and Xhosa", gloss: "I am because we are" },
  { word: "Paying it forward", lang: "English", gloss: "kindness passed on, not paid back" },
];

const WHY = [
  ["Your gift reaches a verified person.", "Every recipient completes identity, address and income checks before receiving support, and a human reviewer makes the final call."],
  ["Small gifts matter here.", "Recipients live on less than $50 a month. A few dollars can restock a street stall, repair a sewing machine or buy seed for the season."],
  ["You can see where it went.", "Give publicly and follow the story you helped write. Give anonymously and use your private Donation Token to follow the same journey without revealing who you are."],
  ["You can hear back.", "Recipients can say thank you: to you directly if you gave publicly, or to the whole community if you chose to stay anonymous."],
  ["Every payment is accounted for.", "Each gift is tied to a unique ledger record from the moment you give until the moment it is paid out. Nothing is left as a loose, unexplained transaction."],
  ["You choose how visible to be.", "Public donors earn recognition and leaderboard points. Anonymous donors are masked in the database itself: no name, no email, nothing linked in any public view."],
];

const BENEFITS = [
  ["Real impact from a small amount.", "When the person you help lives on a very small monthly income, money travels a long way."],
  ["A feeling of connection.", "Seeing a real person's region, small business and thank-you note turns a transaction into a relationship."],
  ["Dignity for the person receiving.", "Recipients are supported as entrepreneurs in the making, not as faces of pity."],
  ["Peace of mind.", "Verified recipients, transparent tracking and a clear ledger mean you know your gift is accounted for."],
  ["Happiness that comes back to you.", "Researchers who study generosity, including a well-known 2008 study in the journal Science by Dunn, Aknin and Norton, found that spending money on other people tends to make us happier than spending it on ourselves."],
  ["Belonging to something larger.", "Join people around the world who decided that where someone was born should not decide whether they get a chance."],
];

export default function AboutPage() {
  return (
    <>
      {/* ------------------------------------------------------------ hero */}
      <section className="pattern-stars relative overflow-hidden bg-lapis-900 text-white">
        <div className="mx-auto grid max-w-6xl items-center gap-8 px-4 py-16 sm:px-6 md:grid-cols-[1.1fr_1fr] md:py-24">
          <div>
            <h1 className="text-5xl font-bold sm:text-6xl">A word for giving that tells the truth.</h1>
            <p className="mt-6 max-w-xl text-xl text-lapis-100">
              <strong className="font-semibold text-white">SadQah</strong> comes from the Arabic <span lang="ar" className="font-arabic text-2xl text-saffron-400">صدقة</span> (<i>ṣadaqah</i>, said “sa-da-qah”): sincere,
              voluntary giving. No minimum, no deadline, no rulebook. One honest act of generosity, from one person to another.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <LinkButton href="/campaigns" variant="give" size="lg">
                Give to someone today
              </LinkButton>
              <a href="#plan" className="inline-flex h-14 items-center rounded-full px-6 text-lg font-semibold text-white ring-1 ring-inset ring-white/40 hover:bg-white/10">
                Plan my giving
              </a>
            </div>
          </div>
          <div className="animate-settle flex flex-col items-center md:items-end" aria-hidden>
            <span lang="ar" dir="rtl" className="font-arabic text-[9rem] leading-none text-saffron-400 sm:text-[12rem]">
              صدقة
            </span>
            <span className="mt-2 font-display text-2xl tracking-wide text-lapis-100">ṣadaqah</span>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ meaning */}
      <section id="name" className="mx-auto grid max-w-6xl scroll-mt-20 gap-12 px-4 py-20 sm:px-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <div>
          <h2 className="text-4xl font-bold">Where the word comes from</h2>
          <p lang="ar" dir="rtl" className="mt-6 text-left font-arabic text-6xl leading-tight text-lapis-700">
            ص د ق
          </p>
          <p className="mt-2 text-ink-soft">The root ṣ-d-q: truth, sincerity, honesty.</p>
        </div>
        <div className="max-w-prose space-y-5 text-lg">
          <p>
            The idea is simple and old: when you give, your generosity is proof that your values are real. In Arabic and Islamic tradition, Sadaqah is giving from the heart. A coin, a meal, a loan you forgive, an hour of your time, a kind word. What matters is the
            sincerity behind it.
          </p>
          <p>
            It is different from <i>Zakat</i>, the fixed annual contribution that Muslims are obliged to make. Sadaqah is open to anyone, at any time, in any amount. A saying attributed to the Prophet Muhammad and recorded in Sahih Muslim puts it plainly: charity does not
            make wealth less.
          </p>
        </div>
      </section>

      <section className="bg-white">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <h2 className="max-w-2xl text-4xl font-bold">You do not need to be Muslim, or religious at all, to understand it.</h2>
          <p className="mt-4 max-w-2xl text-lg text-ink-soft">Almost every culture has its own version of this idea. SadQah borrows the Arabic name because it describes something universal: giving that is honest, quiet and personal.</p>
          <dl className="mt-10 grid gap-x-10 gap-y-6 sm:grid-cols-2">
            {KINDRED.map((k) => (
              <div key={k.word} className="flex items-baseline gap-4 border-t border-line pt-4">
                <Star className="size-4 shrink-0 translate-y-0.5 text-tile-500" />
                <div>
                  <dt className="font-display text-2xl font-semibold">
                    {k.word} <span className="text-base font-normal text-ink-soft">({k.lang})</span>
                  </dt>
                  <dd className="text-ink-soft">{k.gloss}</dd>
                </div>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* ------------------------------------------------------------ why */}
      <section id="why" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
        <div className="grid gap-12 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <div>
            <h2 className="text-4xl font-bold">Why give through SadQah?</h2>
            <p className="mt-4 text-lg text-ink-soft">Most people want to help and hesitate for the same reasons: will it reach someone, who is it helping, does my small amount even matter? SadQah is built to answer those questions.</p>
          </div>
          <ul className="space-y-6">
            {WHY.map(([lead, body]) => (
              <li key={lead} className="border-l-4 border-saffron-400 pl-5">
                <p className="text-lg">
                  <strong className="font-semibold">{lead}</strong> {body}
                </p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ------------------------------------------------------------ benefits */}
      <section className="bg-tile-50">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <h2 className="text-4xl font-bold">What giving does for everyone</h2>
          <p className="mt-4 max-w-2xl text-lg text-ink-soft">People who give often say it does as much for them as for the person who receives. This is what SadQah tries to make easy.</p>
          <ul className="mt-10 grid gap-x-12 gap-y-8 md:grid-cols-2">
            {BENEFITS.map(([lead, body]) => (
              <li key={lead}>
                <p className="font-display text-2xl font-semibold text-tile-700">{lead}</p>
                <p className="mt-1 text-lg">{body}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ------------------------------------------------------------ plan */}
      <section id="plan" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
        <div className="max-w-3xl">
          <h2 className="text-4xl font-bold">Give as little as 1% of your year. Or any amount you choose.</h2>
          <p className="mt-4 text-lg text-ink-soft">
            There is no correct amount, because Sadaqah is voluntary. If you want a starting point, many people give a small, steady share of their yearly income: <strong className="text-ink">1% to 5%</strong>. Move the slider, or type an amount of your own, and see what it
            becomes each month and across the year.
          </p>
        </div>
        <div className="mt-10">
          <GivingCalculator />
        </div>
        <p className="mt-6 max-w-3xl text-base text-ink-soft">
          A note on honesty: Sadaqah is voluntary and is not the same thing as Zakat. The 1% to 5% guide is a suggestion to help you plan generous giving. It is not a religious ruling and does not replace Zakat for people who pay it. If you want guidance on how Zakat applies
          to you, please ask a qualified scholar.
        </p>
      </section>

      {/* ------------------------------------------------------------ promise */}
      <SiteGuide />

      <section id="promise" className="pattern-stars scroll-mt-20 bg-lapis-900 text-white">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <h2 className="max-w-3xl text-4xl font-bold">Our promise: truth, privacy, dignity and a clear trail.</h2>
          <ul className="mt-8 grid gap-6 text-lg text-lapis-100 md:grid-cols-2">
            <li><strong className="text-white">Truth (ṣidq).</strong> We tell you honestly where your money went.</li>
            <li><strong className="text-white">Privacy.</strong> Anonymous means anonymous, enforced in the database itself and not only in the interface.</li>
            <li><strong className="text-white">Dignity.</strong> Every recipient is treated as a partner, never as a spectacle.</li>
            <li><strong className="text-white">A clear trail.</strong> Every donation can be traced from your wallet to a recipient&apos;s and is reconciled automatically.</li>
          </ul>
          <div className="mt-10 flex flex-wrap gap-3">
            <LinkButton href="/campaigns" variant="give" size="lg">
              Give once, give monthly, give quietly
            </LinkButton>
            <LinkButton href="/register?role=recipient" variant="secondary" size="lg">
              I need support
            </LinkButton>
          </div>
        </div>
      </section>
    </>
  );
}