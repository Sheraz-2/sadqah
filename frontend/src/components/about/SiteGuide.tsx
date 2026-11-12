import Link from "next/link";

type Item = { id: string; tab: string; href: string; cta: string; summary: string; points: string[] };

const GUIDE: Item[] = [
  {
    id: "guide-campaigns",
    tab: "Campaigns",
    href: "/campaigns",
    cta: "Browse campaigns",
    summary: "Every campaign is a verified person starting or keeping a tiny business. This is where you choose who to give to.",
    points: [
      "Search by name or business, filter by country, and sort by newest, closest to goal or most supported.",
      "Open a campaign to read the person's story, see how far along it is, and give $1 to $500.",
      "Give publicly to earn recognition and hear a thank-you, or anonymously to stay private.",
    ],
  },
  {
    id: "guide-give",
    tab: "Giving calculator",
    href: "/give",
    cta: "Open the calculator",
    summary: "A planning tool for people who want to give regularly without guessing what is right for them.",
    points: [
      "Enter your yearly income and choose a share of it, or type any amount you like.",
      "Choose how often: every month, once a year or one time, and see what that adds up to over the year.",
      "Nothing is charged while you plan. Money only moves when you choose a person and complete a gift.",
    ],
  },
  {
    id: "guide-about",
    tab: "About",
    href: "/about",
    cta: "You are here",
    summary: "The idea behind SadQah, why we built it this way, and the promises we make to donors and recipients.",
    points: [
      "Where the word ṣadaqah comes from and how other traditions say the same thing.",
      "How verification, privacy and the ledger work, in plain language.",
      "This guide: a short explanation of every tab on the site.",
    ],
  },
  {
    id: "guide-leaderboard",
    tab: "Leaderboard",
    href: "/leaderboard",
    cta: "See the leaderboard",
    summary: "A public thank-you to people who gave openly.",
    points: [
      "Ranks public givers by points and number of gifts, with a country shown beside each name.",
      "Giving anonymously is never ranked, and never will be. Anonymous gifts are invisible here by design.",
      "Sort and filter any column to find yourself or a friend.",
    ],
  },
  {
    id: "guide-track",
    tab: "Track a gift",
    href: "/track",
    cta: "Track a gift",
    summary: "Follow a gift from the moment you give until it reaches the person.",
    points: [
      "Paste your Donation Token to see each step: received, queued, sent and paid out.",
      "A Donation Token is a private code shown once when you give anonymously. Only a scrambled version is stored, so keep your copy somewhere safe.",
      "If you gave with an account, the same history is in your dashboard with no token needed.",
    ],
  },
  {
    id: "guide-accounts",
    tab: "Your account",
    href: "/login",
    cta: "Sign in or register",
    summary: "What appears once you sign in, depending on who you are.",
    points: [
      "Donors get a dashboard with every public gift, thank-you notes and points.",
      "Recipients get a portal to complete verification, tell their story, open a campaign, read messages and send thanks.",
      "Staff reviewers have a separate console for checking identities, moderating messages and watching payouts.",
    ],
  },
];

export function SiteGuide() {
  return (
    <section id="guide" className="scroll-mt-20 bg-white">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <h2 className="max-w-2xl text-4xl font-bold">A guide to every tab</h2>
        <p className="mt-4 max-w-2xl text-lg text-ink-soft">
          Not sure where to start? Here is what each part of the site is for. The menu at the top has the same sections as quick links.
        </p>
        <div className="mt-10 grid gap-6 md:grid-cols-2">
          {GUIDE.map((g) => (
            <article key={g.id} id={g.id} className="scroll-mt-24 rounded-2xl bg-paper p-6 ring-1 ring-line">
              <h3 className="text-2xl font-bold">{g.tab}</h3>
              <p className="mt-2 text-ink-soft">{g.summary}</p>
              <ul className="mt-4 space-y-2">
                {g.points.map((p) => (
                  <li key={p} className="border-l-4 border-saffron-400 pl-4">
                    {p}
                  </li>
                ))}
              </ul>
              {g.cta !== "You are here" && (
                <Link href={g.href} className="mt-5 inline-flex font-semibold text-lapis-700 underline-offset-4 hover:underline">
                  {g.cta} <span aria-hidden>→</span>
                </Link>
              )}
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
