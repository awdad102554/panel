/**
 * 主流模型的最大输出 token 上限预设,用于模型管理表单在填写模型名时自动填入。
 *
 * 数值来源:2026-08 各厂商公开资料/官方文档(上下文窗口 ≠ 输出上限,此处均为
 * 单次请求最大输出 token 数)。只是可编辑的默认值,厂商调整后以官方文档为准。
 */

export interface ModelPreset {
  /** 模型名包含该子串(小写)即命中;按数组顺序先匹配先生效,特殊的放前面。 */
  match: string;
  /** 最大输出 token 数。 */
  maxTokens: number;
}

export const MODEL_MAX_OUTPUT_PRESETS: ModelPreset[] = [
  // DeepSeek:V4 系列官方最大输出 384K;V3 代 deepseek-chat 8K、reasoner 64K。
  { match: "deepseek-v4-pro", maxTokens: 393216 },
  { match: "deepseek-v4-flash", maxTokens: 393216 },
  { match: "deepseek-reasoner", maxTokens: 65536 },
  { match: "deepseek-chat", maxTokens: 8192 },
  // OpenAI:GPT-5.5/5.6 最大输出 128K;gpt-4.1 32K;gpt-4o 16K。
  { match: "gpt-5", maxTokens: 131072 },
  { match: "gpt-4.1", maxTokens: 32768 },
  { match: "gpt-4o", maxTokens: 16384 },
  // Anthropic:Opus 4.8/5、Sonnet 5、Fable 5 最大输出 128K;Haiku 4.5 为 64K。
  { match: "claude-haiku", maxTokens: 65536 },
  { match: "claude", maxTokens: 131072 },
  // Moonshot:K3 官方默认 131072(可设至 1M 减输入);K2.6/K2.7 最大输出 98304。
  { match: "kimi-k3", maxTokens: 131072 },
  { match: "kimi-k2", maxTokens: 98304 },
  // 阿里百炼:Qwen3 代 Max/Plus 官方最大输出 64K;旧 qwen-max 8K。
  { match: "qwen3", maxTokens: 65536 },
  { match: "qwen-max", maxTokens: 8192 },
  // 智谱:GLM-5 代最大输出约 128K;GLM-4 代 8K。
  { match: "glm-5", maxTokens: 131072 },
  { match: "glm-4", maxTokens: 8192 },
];

/** 未命中预设时的通用安全默认值。 */
export const DEFAULT_MAX_TOKENS = 8192;

/**
 * 按模型名查预设的最大输出 token 数(大小写不敏感、子串匹配,
 * 兼容 "deepseek/deepseek-v4-pro" 这类带供应商前缀的写法)。
 * 未命中返回 null,由调用方决定填默认值还是保持用户输入。
 */
export function lookupModelMaxTokens(modelName: string): number | null {
  const name = modelName.trim().toLowerCase();
  if (!name) return null;
  for (const preset of MODEL_MAX_OUTPUT_PRESETS) {
    if (name.includes(preset.match)) return preset.maxTokens;
  }
  return null;
}
