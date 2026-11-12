"use client";

import { useMemo } from "react";
import { Combobox, type ComboOption } from "@/components/ui/Combobox";
import { countryName } from "@/lib/format";
import { regionsFor } from "@/lib/regions";

type Props = {
  label: string;
  /** ISO-2 country the suggestions belong to. Without one the field is a plain text box. */
  country: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  error?: string | null;
  disabled?: boolean;
  className?: string;
};

/** Province / state / region: suggestions for the chosen country only, and any text can still be typed. */
export function RegionField({ country, ...rest }: Props) {
  const options = useMemo<ComboOption[]>(() => regionsFor(country).map((r) => ({ value: r, label: r })), [country]);
  const named = countryName(country);
  return (
    <Combobox
      {...rest}
      key={country /* start fresh when the country changes */}
      options={options}
      allowCustom
      disabled={rest.disabled || !country}
      placeholder={country ? (options.length ? `Type or pick a place in ${named}` : `Type your province or state in ${named}`) : "Choose a country first"}
      emptyText={country ? `Keep typing: anything you enter is kept` : "Choose a country first"}
    />
  );
}
