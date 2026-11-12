import type { Metadata } from "next";
import { GivingCalculator } from "@/components/about/GivingCalculator";

export const metadata: Metadata = { title: "Giving calculator", description: "Plan your giving: 1% to 5% of your yearly income, or any amount you choose." };

export default function GivePage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
      <h1 className="max-w-3xl text-5xl font-bold">How much feels right for you?</h1>
      <p className="mt-4 max-w-2xl text-lg text-ink-soft">
        Many people give 1% to 5% of what they earn in a year. Pick a share or type your own amount. Your income never leaves your browser. The 1% to 5% range is a voluntary suggestion, not a religious ruling or a tax figure.
      </p>
      <div className="mt-10">
        <GivingCalculator />
      </div>
    </div>
  );
}
