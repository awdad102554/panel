/** 仲裁请求类型目录的共用工具:级联选项、模板判定、按内网模板生成请求文本。
 *
 * 生成逻辑与后端 case_submit._fill_template/_fmt_amount 逐条对齐
 * (选项1/标的/开始日期/结束日期/$str 占位,日期零填充"2026年07月29日")。
 */
import type { CatalogItem } from "@/api/virtualCases";

export interface CascaderNode {
  value: number;
  label: string;
  children?: CascaderNode[];
}

/** 类型树 → el-cascader 选项(支持两级叶子:确认劳动关系争议等没有第三层)。 */
export function buildCascaderOptions(catalog: CatalogItem[]): CascaderNode[] {
  const l1map = new Map<number, CascaderNode>();
  const l2map = new Map<string, CascaderNode>();
  for (const item of catalog) {
    const [l1, l2, l3] = item.path;
    if (!l1map.has(l1.id)) l1map.set(l1.id, { value: l1.id, label: l1.name, children: [] });
    const n1 = l1map.get(l1.id)!;
    const key2 = `${l1.id}/${l2.id}`;
    if (!l2map.has(key2)) {
      const n2: CascaderNode = { value: l2.id, label: l2.name, children: [] };
      l2map.set(key2, n2);
      n1.children!.push(n2);
    }
    if (l3) l2map.get(key2)!.children!.push({ value: l3.id, label: l3.name });
  }
  // 两级叶子的 children 为空数组,删掉让 el-cascader 把它当作可选叶子。
  for (const n1 of l1map.values()) {
    for (const n2 of n1.children ?? []) {
      if (!n2.children?.length) delete n2.children;
    }
    if (!n1.children?.length) delete n1.children;
  }
  return [...l1map.values()];
}

export function catalogItemOf(catalog: CatalogItem[], path: number[]): CatalogItem | undefined {
  return catalog.find((c) => c.path.length === path.length && c.path.every((n, i) => n.id === path[i]));
}

/** $str 模板(如工伤保险待遇)需要多选项+逐项金额。 */
export function isMultiTemplate(template: string): boolean {
  return template.includes("$str");
}

/** 期间类请求(工资/二倍工资等):模板含 开始日期/结束日期 占位。 */
export function needsDatesTemplate(template: string): boolean {
  return template.includes("开始日期") || template.includes("结束日期");
}

/** 其他类请求:模板含 $other 占位,需要用户填具体内容。 */
export function needsOtherTemplate(template: string): boolean {
  return template.includes("$other");
}

/** 与后端 _fmt_amount 一致:两位小数去尾零(53015.60→"53015.6",100→"100")。 */
export function fmtAmount(value: number): string {
  return String(parseFloat(value.toFixed(2)));
}

/** YYYY-MM-DD → YYYY年MM月DD日(月日零填充,与内网 moment 格式一致)。 */
export function cnDate(value: string): string {
  const [y, m, d] = value.slice(0, 10).split("-");
  return `${y}年${m}月${d}日`;
}

export interface RequestRowData {
  option: string | null;
  object: number | null;
  items: { name: string; object: number | null }[];
  start_at: string | null;
  end_at: string | null;
  other: string | null; // $other 模板(其他类请求)的具体内容
}

/** 按内网模板生成请求表述;含无法填充的占位时返回 null(与后端 _fill_template 一致)。 */
export function fillRequestTemplate(item: CatalogItem, row: RequestRowData): string | null {
  let out = item.template || "";
  if (!out) return null;
  // 多选项($str)行的金额在明细里:标的占位取明细合计(与后端 build_payload 的求和一致)。
  const obj =
    row.object ??
    (row.items.length && row.items.every((i) => i.object != null)
      ? row.items.reduce((acc, i) => acc + (i.object ?? 0), 0)
      : null);
  if (out.includes("$str")) {
    if (!row.items.length || row.items.some((i) => i.object == null)) return null;
    const enumText = row.items
      .map((i, n) => `（${n + 1}）${i.name}${fmtAmount(i.object!)}元`)
      .join("、");
    out = out.split("$str").join(enumText);
  }
  if (out.includes("$other")) {
    if (!row.other?.trim()) return null;
    out = out.split("$other").join(row.other.trim());
  }
  if (out.includes("选项2")) return null;
  if (out.includes("选项1")) {
    if (!row.option) return null;
    out = out.split("选项1").join(row.option);
  }
  if (out.includes("开始日期")) {
    if (!row.start_at) return null;
    out = out.split("开始日期").join(cnDate(row.start_at));
  }
  if (out.includes("结束日期")) {
    if (!row.end_at) return null;
    out = out.split("结束日期").join(cnDate(row.end_at));
  }
  if (out.includes("标的")) {
    if (obj == null) return null;
    // 优先整替"标的元"(占位形态),避免误伤"标的额"等非占位语境。
    if (out.includes("标的元")) out = out.split("标的元").join(`${fmtAmount(obj)}元`);
    else out = out.split("标的").join(fmtAmount(obj));
  }
  if (!out.endsWith("。")) out += "。";
  return out;
}
