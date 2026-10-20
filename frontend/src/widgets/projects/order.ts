// The ids with `id` swapped with its neighbour among `visible` (the items shown), for ↑ / ↓
export function moved(all: string[], visible: string[], id: string, step: -1 | 1): string[] | null {
  const neighbour = visible[visible.indexOf(id) + step]
  if (!neighbour) return null
  const order = [...all]
  const a = order.indexOf(id)
  const b = order.indexOf(neighbour)
  ;[order[a], order[b]] = [order[b], order[a]]
  return order
}
