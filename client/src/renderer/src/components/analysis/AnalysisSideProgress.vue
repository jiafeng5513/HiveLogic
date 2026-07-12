<template>
  <div class="analysis-side-progress">
    <!-- Agent 实时进度 -->
    <div class="progress-section" v-if="stages.length > 0">
      <div class="section-header">
        <span class="section-icon">⚡</span>
        <span>分析进度</span>
      </div>
      <div class="stage-list">
        <div
          v-for="stage in stageItems"
          :key="stage.key"
          class="stage-row"
          :class="stage.status"
        >
          <span class="stage-icon">{{ stage.icon }}</span>
          <span class="stage-label">{{ stage.label }}</span>
          <span class="stage-time" v-if="stage.duration">{{ stage.duration.toFixed(1) }}s</span>
        </div>
      </div>
    </div>

    <!-- 辩论过程 -->
    <div class="progress-section" v-if="debate">
      <div class="section-header">
        <span class="section-icon">⚖️</span>
        <span>多空辩论</span>
        <span class="round-badge" v-if="debate.totalRounds">
          {{ debate.round }}/{{ debate.totalRounds }}
        </span>
      </div>
      <div class="debate-live">
        <div class="debate-row debate-bull" v-if="debate.bull">
          <span class="debate-tag">📈 多</span>
          <span class="debate-text">{{ truncate(debate.bull, 80) }}</span>
        </div>
        <div class="debate-row debate-bear" v-if="debate.bear">
          <span class="debate-tag">📉 空</span>
          <span class="debate-text">{{ truncate(debate.bear, 80) }}</span>
        </div>
      </div>
    </div>

    <!-- 风险讨论 -->
    <div class="progress-section" v-if="riskDebate">
      <div class="section-header">
        <span class="section-icon">🛡️</span>
        <span>风险评估</span>
      </div>
      <div class="risk-live">
        <div
          v-for="persp in (riskDebate.perspectives || [])"
          :key="persp"
          class="risk-row"
        >
          <span class="risk-tag">{{ perspIcon(persp) }}</span>
          <span class="risk-text">{{ truncate(riskDebate.content?.[persp] || '', 60) }}</span>
        </div>
      </div>
    </div>

    <!-- AI 调研计划 (autonomous mode) -->
    <div class="progress-section" v-if="plan">
      <div class="section-header">
        <span class="section-icon">📋</span>
        <span>AI 调研计划</span>
        <span class="round-badge" v-if="plan.estimated_steps">
          {{ plan.investigation_steps.length }}/{{ plan.estimated_steps }}
        </span>
      </div>
      <div class="plan-steps">
        <div
          v-for="step in plan.investigation_steps"
          :key="step.step"
          class="plan-step-row"
        >
          <div class="plan-step-header">
            <span class="plan-step-num">{{ step.step }}</span>
            <span class="priority-badge" :class="step.priority">{{ priorityLabel(step.priority) }}</span>
            <span class="plan-step-objective">{{ step.objective }}</span>
          </div>
          <div class="plan-step-tools" v-if="step.tools && step.tools.length">
            <span class="tool-tag" v-for="tool in step.tools" :key="tool">{{ tool }}</span>
          </div>
          <div class="plan-step-expected" v-if="step.expected_data">
            <span class="expected-label">预期:</span>
            <span class="expected-text">{{ step.expected_data }}</span>
          </div>
        </div>
      </div>
      <!-- 推理过程 (collapsible) -->
      <div class="reasoning-section" v-if="stepReasoning.length > 0">
        <div class="reasoning-header" @click="reasoningExpanded = !reasoningExpanded">
          <span class="reasoning-toggle">{{ reasoningExpanded ? '▾' : '▸' }}</span>
          <span>推理过程 ({{ stepReasoning.length }})</span>
        </div>
        <div class="reasoning-list" v-show="reasoningExpanded">
          <div
            v-for="(r, idx) in stepReasoning"
            :key="idx"
            class="reasoning-row"
          >
            <div class="reasoning-row-header" @click="toggleReasoning(idx)">
              <span class="reasoning-toggle-sm">{{ expandedReasoning.has(idx) ? '▾' : '▸' }}</span>
              <span class="reasoning-step-tag">Step {{ r.step }}</span>
              <span class="reasoning-phase-tag" :class="r.phase">{{ phaseLabel(r.phase) }}</span>
              <span class="reasoning-content">
                {{ expandedReasoning.has(idx) ? r.content : truncate(r.content, 60) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 思考状态 -->
    <div class="progress-section thinking-section" v-if="thinking && !stages.length">
      <div class="section-header">
        <span class="section-icon thinking-anim">🧠</span>
        <span>思考中...</span>
      </div>
      <div class="thinking-preview">{{ truncate(thinking, 120) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { StageInfo, DebateInfo, RiskDebateInfo, InvestigationPlan, StepReasoning } from '../../service/chatService'

const props = defineProps<{
  stages: StageInfo[]
  debate: DebateInfo | null
  riskDebate: RiskDebateInfo | null
  thinking: string
  mode: string
  plan: InvestigationPlan | null
  stepReasoning: StepReasoning[]
}>()

const stageDefinitions: Record<string, { key: string; label: string }[]> = {
  quick: [
    { key: 'technical', label: '技术分析' },
    { key: 'intel', label: '情报采集' },
    { key: 'decision', label: '综合决策' }
  ],
  deep: [
    { key: 'technical', label: '技术分析' },
    { key: 'intel', label: '情报采集' },
    { key: 'risk', label: '风险评估' },
    { key: 'debate', label: '多空辩论' },
    { key: 'risk_debate', label: '风险讨论' },
    { key: 'skill', label: '策略会诊' },
    { key: 'decision', label: '综合决策' }
  ],
  autonomous: [
    { key: 'autonomous_planner', label: '自主规划' }
  ]
}

const stageItems = computed(() => {
  const defs = stageDefinitions[props.mode] || stageDefinitions.quick
  return defs.map(def => {
    const s = props.stages.find(st => st.stage === def.key)
    let status = 'pending'
    let icon = '○'
    let duration: number | undefined

    if (s) {
      status = s.status
      duration = s.duration
      if (s.status === 'completed') icon = '✅'
      else if (s.status === 'running') icon = '🔄'
      else if (s.status === 'error') icon = '❌'
    }

    return { ...def, status, icon, duration }
  })
})

function perspIcon(persp: string) {
  if (persp.includes('aggressive') || persp.includes('激进')) return '🔥'
  if (persp.includes('conservative') || persp.includes('保守')) return '🛡️'
  return '⚖️'
}

function truncate(text: string, max: number) {
  return text.length > max ? text.slice(0, max) + '...' : text
}

// 调研计划 — 推理过程折叠状态
const reasoningExpanded = ref(true)
const expandedReasoning = ref<Set<number>>(new Set())

function toggleReasoning(idx: number) {
  const next = new Set(expandedReasoning.value)
  if (next.has(idx)) next.delete(idx)
  else next.add(idx)
  expandedReasoning.value = next
}

function priorityLabel(priority: string) {
  if (priority === 'high') return '高'
  if (priority === 'medium') return '中'
  return '低'
}

function phaseLabel(phase: string) {
  if (phase === 'planning') return '规划'
  return '执行'
}
</script>

<style scoped>
.analysis-side-progress {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
}

.progress-section {
  background: #1e2a36;
  border-radius: 8px;
  padding: 10px 12px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #b0c4d8;
  margin-bottom: 8px;
}

.section-icon {
  font-size: 14px;
}

.round-badge {
  margin-left: auto;
  font-size: 11px;
  background: #2a3f52;
  padding: 2px 6px;
  border-radius: 4px;
  color: #8bb8d4;
}

/* Stage list */
.stage-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stage-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 6px;
  border-radius: 4px;
}

.stage-row.running {
  background: #1a3050;
}

.stage-icon {
  width: 18px;
  text-align: center;
  font-size: 12px;
}

.stage-label {
  flex: 1;
  color: #ccc;
}

.stage-time {
  font-size: 11px;
  color: #888;
}

/* Debate live */
.debate-live, .risk-live {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.debate-row, .risk-row {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  font-size: 11px;
}

.debate-tag, .risk-tag {
  flex-shrink: 0;
  font-size: 12px;
}

.debate-text, .risk-text {
  color: #aaa;
  line-height: 1.4;
}

.debate-bull { border-left: 2px solid #52c41a; padding-left: 6px; }
.debate-bear { border-left: 2px solid #ff4d4f; padding-left: 6px; }

/* Thinking */
.thinking-section .thinking-preview {
  font-size: 11px;
  color: #888;
  line-height: 1.4;
}

.thinking-anim {
  animation: pulse 1.2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* AI 调研计划 */
.plan-steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.plan-step-row {
  background: #18222e;
  border-radius: 6px;
  padding: 6px 8px;
  border-left: 2px solid #2a3f52;
}

.plan-step-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.plan-step-num {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #2a3f52;
  color: #8bb8d4;
  border-radius: 50%;
  font-size: 10px;
  font-weight: 600;
}

.priority-badge {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 600;
}

.priority-badge.high {
  background: #3a1a1a;
  color: #ff4d4f;
}

.priority-badge.medium {
  background: #3a2e00;
  color: #d29922;
}

.priority-badge.low {
  background: #2a2a2a;
  color: #888;
}

.plan-step-objective {
  flex: 1;
  color: #ccc;
  line-height: 1.4;
}

.plan-step-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
  padding-left: 24px;
}

.tool-tag {
  font-size: 10px;
  background: #1a3050;
  color: #8bb8d4;
  padding: 1px 5px;
  border-radius: 3px;
}

.plan-step-expected {
  display: flex;
  gap: 4px;
  margin-top: 3px;
  padding-left: 24px;
  font-size: 10px;
  color: #888;
  line-height: 1.4;
}

.expected-label {
  color: #667788;
  flex-shrink: 0;
}

.expected-text {
  color: #888;
}

/* 推理过程 */
.reasoning-section {
  margin-top: 8px;
  border-top: 1px solid #2a3f52;
  padding-top: 6px;
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #8bb8d4;
  cursor: pointer;
  user-select: none;
  padding: 2px 0;
}

.reasoning-header:hover {
  color: #b0c4d8;
}

.reasoning-toggle {
  font-size: 10px;
  width: 12px;
}

.reasoning-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 4px;
}

.reasoning-row {
  background: #18222e;
  border-radius: 4px;
  padding: 4px 6px;
}

.reasoning-row-header {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  font-size: 11px;
  cursor: pointer;
  user-select: none;
}

.reasoning-toggle-sm {
  flex-shrink: 0;
  font-size: 10px;
  color: #667788;
  width: 10px;
  padding-top: 1px;
}

.reasoning-step-tag {
  flex-shrink: 0;
  font-size: 10px;
  color: #8bb8d4;
  background: #2a3f52;
  padding: 1px 5px;
  border-radius: 3px;
}

.reasoning-phase-tag {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
}

.reasoning-phase-tag.planning {
  background: #2a1a3a;
  color: #c084fc;
}

.reasoning-phase-tag.execution {
  background: #1a2e1a;
  color: #52c41a;
}

.reasoning-content {
  flex: 1;
  color: #aaa;
  line-height: 1.4;
  word-break: break-word;
}
</style>
