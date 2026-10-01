import type { BudgetEntry } from '../../api'

export const LEVEL_NAMES = ['Category', 'Sub-category', 'Sub-sub-category', 'Sub-sub-sub-category']

export function formatMoney(value: number, currency: string, decimals = 0): string {
  const text = value.toLocaleString([], { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  return currency ? `${text} ${currency}` : text
}

export const isIncome = (category: string) => category.trim().toLowerCase() === 'income'

// Category tree of one month's entries: every node's total includes everything under it;
// `own` are the entries filed exactly at that node
export type TreeNode = { name: string; path: string[]; total: number; own: BudgetEntry[]; children: TreeNode[] }

export function buildTree(entries: BudgetEntry[]): TreeNode[] {
  const root: TreeNode = { name: '', path: [], total: 0, own: [], children: [] }
  for (const e of entries) {
    let node = root
    node.total += e.amount
    e.path.forEach((name, i) => {
      let child = node.children.find((c) => c.name === name)
      if (!child) {
        child = { name, path: e.path.slice(0, i + 1), total: 0, own: [], children: [] }
        node.children.push(child)
      }
      child.total += e.amount
      node = child
    })
    node.own.push(e)
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => b.total - a.total)
    nodes.forEach((n) => sort(n.children))
  }
  sort(root.children)
  // Income first, then spending
  root.children.sort((a, b) => Number(isIncome(b.name)) - Number(isIncome(a.name)))
  return root.children
}
