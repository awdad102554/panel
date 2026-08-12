<script setup lang="ts">
/** 预登记仲裁请求编辑器:选类型(三级)+金额等结构化字段,按内网模板自动生成
 * 请求文本,文本可手动编辑(编辑后不再自动重生成,可点"自动生成"复位)。
 * 旧数据的自由文本行以"自由文本"行展示,不强制结构化。 */
import { computed } from "vue";

import type { CatalogItem } from "@/api/virtualCases";
import {
  buildCascaderOptions,
  catalogItemOf,
  fillRequestTemplate,
  isMultiTemplate,
  needsDatesTemplate,
  needsOtherTemplate,
} from "@/utils/requestCatalog";

export interface ReqRow {
  free: boolean; // true=自由文本行(旧数据/自定义)
  text: string; // 请求文本(自动生成,可编辑;入库 requests)
  touched: boolean; // 用户手动改过文本后不再自动重生成
  path: number[]; // 类型 cascader 绑定(三级;确认劳动关系等两级叶子为两级)
  path_names?: string[]; // 类型名称(编辑加载时带入;目录拉取失败时保存原样保留用)
  option: string | null;
  object: number | null;
  items: { name: string; object: number | null }[];
  start_at: string | null;
  end_at: string | null;
  other: string; // $other 模板(其他类请求)的具体内容
}

const props = defineProps<{
  rows: ReqRow[];
  catalog: CatalogItem[];
}>();

const cascaderOptions = computed(() => buildCascaderOptions(props.catalog));

function itemOf(row: ReqRow): CatalogItem | undefined {
  return catalogItemOf(props.catalog, row.path);
}

function isMulti(row: ReqRow): boolean {
  return isMultiTemplate(itemOf(row)?.template ?? "");
}

function needsDates(row: ReqRow): boolean {
  return needsDatesTemplate(itemOf(row)?.template ?? "");
}

function needsOther(row: ReqRow): boolean {
  return needsOtherTemplate(itemOf(row)?.template ?? "");
}

function optionsOf(row: ReqRow): string[] {
  return itemOf(row)?.options ?? [];
}

/** 结构化字段变化时自动重生成文本(用户手动改过则不动,避免覆盖人工编辑)。 */
function regen(row: ReqRow) {
  if (row.touched) return;
  const item = itemOf(row);
  if (!item) return;
  const text = fillRequestTemplate(item, row);
  if (text) row.text = text;
}

/** 手动"自动生成":强制按模板复位文本,并解除编辑锁定。 */
function forceRegen(row: ReqRow) {
  row.touched = false;
  const item = itemOf(row);
  if (!item) return;
  const text = fillRequestTemplate(item, row);
  if (text) row.text = text;
}

function onPathChange(row: ReqRow) {
  // 换类型后,原选项/金额/期间/其他内容大概率不再适用,清空重选(陈旧金额会产出错误文本)。
  const item = itemOf(row);
  if (row.option && !(item?.options ?? []).includes(row.option)) row.option = null;
  row.items = [];
  row.object = null;
  row.start_at = null;
  row.end_at = null;
  row.other = "";
  row.touched = false; // 新类型重新开始自动生成
  regen(row);
}

function onItemsChange(row: ReqRow, names: string[]) {
  const old = new Map(row.items.map((i) => [i.name, i.object]));
  row.items = names.map((n) => ({ name: n, object: old.get(n) ?? null }));
  regen(row);
}

function itemsSum(row: ReqRow): number | null {
  if (!row.items.length || row.items.some((i) => i.object == null)) return null;
  return row.items.reduce((acc, i) => acc + (i.object ?? 0), 0);
}

function addStructured() {
  props.rows.push({
    free: false,
    text: "",
    touched: false,
    path: [],
    option: null,
    object: null,
    items: [],
    start_at: null,
    end_at: null,
    other: "",
  });
}

function addFree() {
  props.rows.push({
    free: true,
    text: "",
    touched: false,
    path: [],
    option: null,
    object: null,
    items: [],
    start_at: null,
    end_at: null,
    other: "",
  });
}
</script>

<template>
  <div class="req-editor">
    <div v-for="(row, idx) in rows" :key="idx" class="req-card">
      <div class="req-card-header">
        <span>
          请求 {{ idx + 1 }}
          <el-tag v-if="row.free" size="small" type="info" effect="plain">自由文本</el-tag>
          <el-tag v-else size="small" type="success" effect="plain">结构化</el-tag>
        </span>
        <el-button size="small" text type="danger" @click="rows.splice(idx, 1)">删除</el-button>
      </div>
      <template v-if="!row.free">
        <div class="req-fields">
          <el-cascader
            v-model="row.path"
            :options="cascaderOptions"
            placeholder="请求类型(确认劳动关系等为两级)"
            style="width: 320px"
            @change="onPathChange(row)"
          />
          <template v-if="isMulti(row)">
            <el-select
              :model-value="row.items.map((i) => i.name)"
              multiple
              filterable
              placeholder="费用项(可多选)"
              style="width: 300px"
              @update:model-value="onItemsChange(row, $event)"
            >
              <el-option v-for="o in optionsOf(row)" :key="o" :label="o" :value="o" />
            </el-select>
            <span class="sum-hint">合计: {{ itemsSum(row) ?? "—" }} 元</span>
          </template>
          <template v-else>
            <el-select
              v-model="row.option"
              clearable
              filterable
              placeholder="第四级选项"
              style="width: 240px"
              :disabled="!optionsOf(row).length"
              @change="regen(row)"
            >
              <el-option v-for="o in optionsOf(row)" :key="o" :label="o" :value="o" />
            </el-select>
            <el-input-number
              v-model="row.object"
              :min="0"
              :precision="2"
              :controls="false"
              placeholder="金额(元)"
              style="width: 130px"
              @change="regen(row)"
            />
          </template>
        </div>
        <div v-if="needsDates(row)" class="req-fields">
          <el-date-picker
            v-model="row.start_at"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="期间起(开始日期)"
            style="width: 190px"
            @change="regen(row)"
          />
          <el-date-picker
            v-model="row.end_at"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="期间止(结束日期)"
            style="width: 190px"
            @change="regen(row)"
          />
        </div>
        <div v-if="needsOther(row)" class="req-fields">
          <el-input
            v-model="row.other"
            placeholder="其他类请求的具体内容,如:未缴纳住房公积金损失"
            style="width: 400px"
            @input="regen(row)"
          />
        </div>
        <div v-if="isMulti(row) && row.items.length" class="items-amounts">
          <div v-for="(it, iIdx) in row.items" :key="it.name" class="item-amount">
            <span class="item-name">{{ iIdx + 1 }}. {{ it.name }}</span>
            <el-input-number
              v-model="it.object"
              :min="0"
              :precision="2"
              :controls="false"
              placeholder="金额(元)"
              style="width: 130px"
              @change="regen(row)"
            />
          </div>
        </div>
      </template>
      <div class="req-text">
        <el-input
          v-model="row.text"
          type="textarea"
          :rows="2"
          :placeholder="
            row.free
              ? '请具体明确地填写仲裁请求,例如:请求裁决被申请人支付拖欠的工资XXXX元。'
              : '选好类型和金额后自动生成,可手动修改'
          "
          @input="row.touched = true"
        />
        <el-button
          v-if="!row.free && itemOf(row)"
          size="small"
          text
          type="primary"
          class="regen-btn"
          title="按类型模板自动生成文本(覆盖手动修改)"
          @click="forceRegen(row)"
        >
          自动生成
        </el-button>
      </div>
    </div>
    <div class="req-actions">
      <el-button size="small" text type="primary" :disabled="!catalog.length" @click="addStructured">
        + 添加请求
      </el-button>
      <el-button size="small" text @click="addFree">+ 自定义文本请求</el-button>
      <span v-if="!catalog.length" class="load-hint">
        请求类型目录未加载(内网字典不可用),可先自定义文本填写
      </span>
    </div>
  </div>
</template>

<style scoped>
.req-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}

.req-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 8px;
}

.req-card-header .el-tag {
  margin-left: 6px;
}

.req-fields {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.sum-hint {
  font-size: 13px;
  color: var(--el-text-color-regular);
  align-self: center;
}

.items-amounts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px 16px;
  margin-bottom: 8px;
}

.item-amount {
  display: flex;
  align-items: center;
  gap: 8px;
}

.item-name {
  font-size: 13px;
  color: var(--el-text-color-regular);
  flex: 1;
}

.req-text {
  position: relative;
}

.regen-btn {
  position: absolute;
  right: 4px;
  bottom: 2px;
}

.req-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.load-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
