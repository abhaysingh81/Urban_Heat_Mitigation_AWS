import { CITY_IDS, CITY_NAME, type CityId } from '../lib/data';

export function Seg<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" aria-pressed={o.id === value} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function CityTabs({ value, onChange }: { value: CityId; onChange: (c: CityId) => void }) {
  return (
    <Seg
      label="City"
      value={value}
      onChange={onChange}
      options={CITY_IDS.map((id) => ({ id, label: CITY_NAME[id] }))}
    />
  );
}
