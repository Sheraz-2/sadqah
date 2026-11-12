"use client";

import { useMemo } from "react";
import type { ColDef } from "ag-grid-community";
import { get } from "@/lib/api";
import { countryName, formatNumber } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { DataGrid } from "@/components/grids/DataGrid";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import type { LeaderboardRow } from "@/types/api";

export default function LeaderboardPage() {
  const board = useAsync((s) => get<{ items: LeaderboardRow[] }>("/public/leaderboard?limit=100", s), []);
  const columns = useMemo<ColDef<LeaderboardRow>[]>(
    () => [
      { field: "rank", headerName: "Rank", width: 90, flex: 0, filter: "agNumberColumnFilter" },
      { field: "donor_label", headerName: "Donor", flex: 2 },
      { headerName: "Country", valueGetter: (p) => countryName(p.data?.country_code) || "", flex: 1 },
      { field: "points", headerName: "Points", filter: "agNumberColumnFilter", valueFormatter: (p) => formatNumber(Number(p.value)) },
      { field: "donation_count", headerName: "Gifts", filter: "agNumberColumnFilter" },
    ],
    [],
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
      <h1 className="text-5xl font-bold">Leaderboard</h1>
      <p className="mt-4 max-w-2xl text-lg text-ink-soft">Thank you to everyone who gave publicly. Giving anonymously is never ranked, and never will be.</p>

      <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_20rem]">
        <div>
          {board.error && !board.data ? (
            <Alert tone="bad" title="We could not load the leaderboard.">
              Please refresh in a moment.
            </Alert>
          ) : (
            <DataGrid<LeaderboardRow>
              label="Leaderboard"
              rows={board.data?.items ?? null}
              loading={board.loading}
              columns={columns}
              rowId={(r) => String(r.rank)}
              paginate={25}
              emptyText="No public gifts yet. Be the first."
            />
          )}
        </div>
        <Card className="h-fit">
          <h2 className="text-2xl font-semibold">How points work</h2>
          <ul className="mt-3 space-y-2 text-ink-soft">
            <li>You earn 1 point for every $1 you give publicly (at least 1 point per gift).</li>
            <li>Only public gifts count. Anonymous gifts are not linked to any account, so they cannot earn points.</li>
            <li>You can hide yourself from this page at any time in your giving settings.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
