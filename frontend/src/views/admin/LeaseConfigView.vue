<template>
  <div v-loading="loading" class="page-stack">
    <el-card shadow="never">
      <template #header>
        <div class="header">
          <div>
            <div class="section-kicker">Policy</div>
            租约 / 代理配置
          </div>
          <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
        </div>
      </template>

      <el-form v-if="form" :model="form" label-width="200px" class="config-form">
        <section class="config-block">
          <h3>网关与调度</h3>
          <el-form-item label="启用网关">
            <el-switch v-model="form.gateway_enabled" />
          </el-form-item>
          <el-form-item label="调度策略">
            <el-select v-model="form.scheduler_strategy" style="width: 240px">
              <el-option label="剩余用量优先" value="remaining_first" />
              <el-option label="临期优先" value="expiry_first" />
            </el-select>
            <div class="form-hint">
              剩余用量优先：优先租用套餐剩余额度更多的号。临期优先：优先租用计费周期剩余天数更少的号。
            </div>
          </el-form-item>
          <el-form-item label="租约过期模式">
            <el-select v-model="form.lease_expiry_mode" style="width: 240px">
              <el-option label="固定时长" value="fixed_duration" />
              <el-option label="计费周期" value="billing_cycle" />
            </el-select>
          </el-form-item>
        </section>

        <section class="config-block">
          <h3>租约限制</h3>
          <el-form-item label="租用人最低用量%">
            <el-input-number v-model="form.lease_min_renter_usage_percent" :min="0" :max="100" />
          </el-form-item>
          <el-form-item label="Pro 最大并发">
            <el-input-number v-model="form.lease_max_concurrent_pro" :min="0" />
          </el-form-item>
          <el-form-item label="Pro+ 最大并发">
            <el-input-number v-model="form.lease_max_concurrent_pro_plus" :min="0" />
          </el-form-item>
          <el-form-item label="Ultra 最大并发">
            <el-input-number v-model="form.lease_max_concurrent_ultra" :min="0" />
          </el-form-item>
        </section>

        <section class="config-block">
          <h3>自动号池</h3>
          <el-form-item label="启用自动号池">
            <el-switch v-model="form.auto_pool_enabled" />
          </el-form-item>
          <el-form-item label="周期刷新时移除">
            <el-switch v-model="form.auto_pool_remove_on_cycle_refresh" />
          </el-form-item>
        </section>

        <section class="config-block last">
          <h3>其他</h3>
          <el-form-item label="排除自身账号">
            <el-switch v-model="form.exclude_self_account" />
          </el-form-item>
          <div class="form-hint exclude-hint">
            打开后，不会把绑在租用人名下的号租给本人。
          </div>
        </section>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as proxyApi from '@/api/proxy'
import type { ProxyConfig } from '@/types'

const loading = ref(false)
const saving = ref(false)
const form = ref<ProxyConfig | null>(null)

async function loadData() {
  loading.value = true
  try {
    const data = await proxyApi.getProxyConfig()
    form.value = {
      ...data,
      gateway_enabled: data.gateway_enabled ?? true,
      scheduler_strategy:
        data.scheduler_strategy === 'remaining_first'
          ? 'remaining_first'
          : 'expiry_first',
      lease_expiry_mode:
        data.lease_expiry_mode === 'fixed_duration'
          ? 'fixed_duration'
          : 'billing_cycle',
      auto_pool_join_rules: data.auto_pool_join_rules ?? [
        { remaining_days: 5, remaining_usage_percent: 50 },
      ],
    }
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  if (!form.value) return
  saving.value = true
  try {
    form.value = await proxyApi.updateProxyConfig(form.value)
    ElMessage.success('配置已保存')
  } finally {
    saving.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.config-form {
  max-width: 760px;
}
.config-block {
  padding: 4px 0 8px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.config-block.last {
  border-bottom: 0;
}
.config-block h3 {
  margin: 0 0 16px;
  font-size: 13px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
.form-hint {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--muted);
}
.exclude-hint {
  margin: -12px 0 0 200px;
}
</style>
