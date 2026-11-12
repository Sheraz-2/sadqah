"use client";

import { useMemo } from "react";
import { Combobox, type ComboOption } from "@/components/ui/Combobox";
import { COUNTRIES, FEATURED } from "@/lib/countries";

const OPTIONS: ComboOption[] = COUNTRIES.map((c) => ({ value: c.code, label: c.name, badge: c.code, meta: `+${c.dial}`, keywords: c.search }));

type Props = {
  label: string;
  value: string;
  onChange: (code: string) => void;
  placeholder?: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  disabled?: boolean;
  className?: string;
  /** e.g. "All countries": adds a first row that clears the choice. */
  anyLabel?: string;
};

/** Every country, searchable by name, ISO code or common nickname (UK, USA, UAE...). The value is the ISO-2 code. */
export function CountrySelect({ placeholder = "Type a country…", ...rest }: Props) {
  const options = useMemo(() => OPTIONS, []);
  return <Combobox {...rest} options={options} placeholder={placeholder} featured={FEATURED} featuredLabel="Where most recipients live" emptyText="No country matches that" />;
}
