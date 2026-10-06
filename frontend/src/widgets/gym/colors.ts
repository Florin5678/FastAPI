// Each workout type keeps one colour everywhere (the Gym page's calendar and its Totals chart,
// in every month): the server gives each type a slot (gym.type_colors: its place in the user's
// list of workout types, shown and hidden alike), which picks one of the 12 validated
// palette colours (.gym-series-N in gym.css). A type the server didn't list yet gets a slot
// from its name, so it's stable too.
export const COLOR_SLOTS = 12

export function seriesSlot(kind: string, colors: Record<string, number>): number {
  if (colors[kind]) return colors[kind]
  let hash = 0
  for (const ch of kind) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return (hash % COLOR_SLOTS) + 1
}
