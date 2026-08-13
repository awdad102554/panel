/** 事实理由拼接(与后端 case_submit.compose_party_facts/compose_case_facts 逐条对齐,
 * 2026-08-13 内网审核通过案件样本总结的四段式):
 * 入职段(空/0 片段省略) + 合同社保段 + 补充事实 + 因主因段;多申请人主体"申请人N"。
 * 纯旧数据(无结构化字段、facts 为整段叙述)直接用叙述原文,不虚构合同社保段。 */

export interface FactParty {
  entry_date?: string | null;
  work_place?: string | null;
  position?: string | null;
  monthly_wage?: string | null;
  is_sign_labor_contract?: number | null;
  is_pay_social_insurance?: number | null;
  main_causes?: string[];
  facts?: string | null;
}

export function composePartyFacts(
  p: FactParty,
  seq = 1,
  total = 1,
  fallbackSign = 1,
  fallbackIns = 1,
  overrideCauses?: string[],
): string {
  const subj = total <= 1 ? "本人" : `申请人${seq}`;
  const facts = (p.facts ?? "").trim().replace(/。+$/, "");
  const causes = (overrideCauses ?? p.main_causes ?? []).map((c) => c.trim()).filter(Boolean);
  // 严格校验,与后端 _to_date_str/_to_float 口径一致(脏数据不生成怪文本)
  const entry = /^\d{4}-\d{2}-\d{2}$/.test(p.entry_date ?? "") ? p.entry_date! : null;
  const wageRaw = String(p.monthly_wage ?? "").replace(/,/g, "");
  // 去尾零必须与后端 _fmt_amount 一致:toFixed(2) 后 parseFloat
  // (直接正则去尾零会把 "4000" 误成 "4")。
  const wageNum = /^\d+(\.\d+)?$/.test(wageRaw) ? parseFloat(wageRaw) : NaN;
  const wage = Number.isFinite(wageNum) && wageNum ? String(parseFloat(wageNum.toFixed(2))) : null;
  const structured = !!(
    entry ||
    p.work_place ||
    p.position ||
    wage ||
    p.is_sign_labor_contract != null ||
    p.is_pay_social_insurance != null
  );
  if (!structured && facts) {
    return facts + "。" + (causes.length ? `因${causes.join("，")}。` : "");
  }
  let out = "";
  const tail: string[] = [];
  if (p.work_place) tail.push(`实际工作地点${p.work_place}`);
  if (p.position) tail.push(`工作岗位为${p.position}`);
  if (wage) tail.push(`月工资标准为${wage}元`);
  if (entry) {
    const [y, m, d] = entry.split("-");
    out += `${subj}于${y}年${m}月${d}日入职被申请人处`;
    if (tail.length) out += ", " + tail.join("，");
    out += "。";
  } else if (tail.length) {
    // 没填入职时间但填了地点/岗位/工资:片段不丢
    out += tail.join("，") + "。";
  }
  const sign = (p.is_sign_labor_contract ?? fallbackSign) === 0 ? "没有" : "有";
  const ins = (p.is_pay_social_insurance ?? fallbackIns) === 0 ? "没有" : "有";
  // 合同社保段沿用"本人"(段落开头已点明申请人N,再用编号读三遍佶屈)
  out += `本人入职后，被申请人${sign}与本人签订书面劳动合同,${ins}为本人缴纳社会保险费`;
  if (facts) out += `;${facts}。`;
  if (causes.length) out += `${facts ? "因" : ";因"}${causes.join("，")}。`;
  if (!facts && !causes.length) out += "。";
  return out;
}

/** 一案完整事实理由:逐申请人分段 + 固定结尾。caseCauses(对话框勾选区)覆盖第一申请人段。 */
export function composeCaseFacts(
  parties: FactParty[],
  opts: { sign?: number; ins?: number; caseCauses?: string[] } = {},
): string {
  const total = parties.length;
  const paras = parties.map((p, i) =>
    composePartyFacts(
      p,
      i + 1,
      total,
      opts.sign ?? 1,
      opts.ins ?? 1,
      i === 0 && opts.caseCauses ? opts.caseCauses : undefined,
    ),
  );
  const ending = "为维护本人合法权益，特提出申请，望裁如所请。";
  // 单申请人:一段到底,不换行(与内网 content 样例一致)
  return total <= 1 ? (paras[0] ?? "") + ending : [...paras, ending].join("\n");
}
