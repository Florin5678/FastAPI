// Each workout type keeps one colour everywhere (the Gym page's calendar and its Totals chart):
// its place in the routine list picks one of the 8 validated palette slots (.gym-series-N in
// gym.css). Types not in the list get a slot from their name, so it stays the same too.
export function seriesSlot(kind: string, kinds: string[]): number {
  const i = kinds.indexOf(kind)
  if (i >= 0) return (i % 8) + 1
  let hash = 0
  for (const ch of kind) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return (hash % 8) + 1
}
