<template>
  <div class="chat-input-area">
    <!-- 模式选择 -->
    <div class="chat-input-toolbar">
      <div class="mode-selector">
        <button
          v-for="mode in availableModes"
          :key="mode.id"
          class="mode-btn"
          :class="{ active: currentMode === mode.id }"
          :title="mode.desc"
          @click="$emit('mode-change', mode.id)"
        >
          {{ mode.label }}
        </button>
      </div>
      <div v-if="skills.length" class="skill-selector" @click="showSkillDropdown = !showSkillDropdown">
        <span class="skill-label">{{ selectedSkillName || '⚖️ 无偏见' }}</span>
        <span class="skill-arrow">▾</span>
        <!-- 技能下拉 -->
        <div v-if="showSkillDropdown" class="skill-dropdown">
          <div
            class="skill-option neutral-hint"
            :class="{ selected: selectedSkills.length === 0 }"
            @click.stop="$emit('skill-toggle', '')"
          >
            <span class="skill-option-name">⚖️ 无偏见（中性分析）</span>
          </div>
          <div
            v-for="skill in skills"
            :key="skill.id"
            class="skill-option"
            :class="{ selected: selectedSkills.includes(skill.id) }"
            @click.stop="$emit('skill-toggle', skill.id)"
          >
            <span class="skill-option-name">{{ skill.name }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 图片预览区 -->
    <div v-if="attachedImages.length > 0" class="image-preview-area">
      <div
        v-for="(img, index) in attachedImages"
        :key="index"
        class="image-preview-item"
      >
        <img :src="img" alt="attachment" />
        <button
          class="image-remove-btn"
          title="移除"
          @click="removeImage(index)"
        >×</button>
      </div>
    </div>

    <!-- 输入框 -->
    <div
      class="chat-input-wrapper"
      :class="{ 'drag-over': isDragOver }"
      @drop="onDrop"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
    >
      <input
        ref="fileInputRef"
        type="file"
        accept="image/*"
        multiple
        style="display:none"
        @change="onFileChange"
      />
      <button
        class="chat-attach-btn"
        title="上传图片 (可多选)"
        @click="triggerFileInput"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
          <path d="M14.5 6.5L8 13l-6.5-6.5a4.5 4.5 0 0 1 6.4-6.4l.1.1.1-.1a4.5 4.5 0 0 1 6.4 6.4z" fill="none" stroke="currentColor" stroke-width="1.2"/>
        </svg>
      </button>
      <textarea
        ref="inputRef"
        v-model="inputText"
        class="chat-input"
        rows="1"
        :placeholder="placeholder"
        @keydown="handleKeydown"
        @input="autoResize"
        @paste="onPaste"
      ></textarea>
      <button
        v-if="isStreaming"
        class="chat-stop-btn"
        title="停止生成"
        @click="$emit('stop')"
      >
        ■
      </button>
      <button
        v-else
        class="chat-send-btn"
        :disabled="!inputText.trim() && attachedImages.length === 0"
        title="发送 (Enter)"
        @click="send"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M1 1.5l14 6.5-14 6.5v-5l8-1.5-8-1.5z"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import type { ChatMode, AgentSkill } from '../../service/chatService'

const props = defineProps<{
  currentMode: ChatMode
  allowedModes: ChatMode[]
  skills: AgentSkill[]
  selectedSkills: string[]
  isStreaming: boolean
}>()

const emit = defineEmits<{
  'send': [text: string, images: string[]]
  'stop': []
  'mode-change': [mode: ChatMode]
  'skill-toggle': [skillId: string]
}>()

const inputRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const inputText = ref('')
const showSkillDropdown = ref(false)
const attachedImages = ref<string[]>([])
const isDragOver = ref(false)

// 单张图片大小上限 ~5MB (base64 后)
const MAX_IMAGE_SIZE = 5 * 1024 * 1024
const MAX_IMAGES = 4

const modeLabels: Record<ChatMode, { label: string; desc: string }> = {
  chat: { label: '对话', desc: '自由对话，纯 LLM 问答' },
  quick: { label: '快速', desc: '⚡ 快速分析 (tech + intel → decision)' },
  deep: { label: '深度', desc: '🔬 深度分析，含辩论 + 策略评估' },
  plan: { label: '计划', desc: '📋 先生成计划后执行' }
}

const availableModes = computed(() =>
  props.allowedModes.map(id => ({ id, ...modeLabels[id] }))
)

const selectedSkillName = computed(() => {
  if (props.selectedSkills.length === 0) return ''
  const skill = props.skills.find(s => s.id === props.selectedSkills[0])
  return skill?.name || ''
})

const placeholder = computed(() => {
  switch (props.currentMode) {
    case 'chat': return '输入问题...'
    case 'quick': return '输入股票代码，快速分析...'
    case 'deep': return '输入标的进行深度分析...'
    case 'plan': return '描述分析目标...'
    default: return '输入问题...'
  }
})

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function send() {
  const text = inputText.value.trim()
  const images = [...attachedImages.value]
  if (!text && images.length === 0) return

  // 斜杠命令解析 (仅在有文本且无图片时生效)
  if (text.startsWith('/mode ') && images.length === 0) {
    const mode = text.slice(6).trim() as ChatMode
    if (props.allowedModes.includes(mode)) {
      emit('mode-change', mode)
    }
    inputText.value = ''
    return
  }

  emit('send', text, images)
  inputText.value = ''
  attachedImages.value = []
  nextTick(() => autoResize())
}

// ==================== 图片处理 ====================

/**
 * 将 File 转为 data URL (base64)
 */
function fileToDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

/**
 * 处理 File 列表, 转为 data URL 并追加到 attachedImages (受 MAX_IMAGES / MAX_IMAGE_SIZE 限制)
 */
async function handleFiles(files: FileList | File[]) {
  const arr = Array.from(files).filter(f => f.type.startsWith('image/'))
  for (const file of arr) {
    if (attachedImages.value.length >= MAX_IMAGES) break
    if (file.size > MAX_IMAGE_SIZE) continue
    try {
      const dataUrl = await fileToDataURL(file)
      attachedImages.value.push(dataUrl)
    } catch {
      // 跳过读取失败的文件
    }
  }
}

function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  const imageFiles: File[] = []
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) imageFiles.push(file)
    }
  }
  if (imageFiles.length > 0) {
    e.preventDefault()
    handleFiles(imageFiles)
  }
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = false
  if (e.dataTransfer?.files) {
    handleFiles(e.dataTransfer.files)
  }
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = true
}

function onDragLeave(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = false
}

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files) {
    handleFiles(target.files)
    target.value = '' // 允许重复选择同一文件
  }
}

function removeImage(index: number) {
  attachedImages.value.splice(index, 1)
}

function triggerFileInput() {
  fileInputRef.value?.click()
}

function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

function focus() {
  inputRef.value?.focus()
}

defineExpose({ focus })
</script>

<style scoped>
.chat-input-area {
  border-top: 1px solid #333;
  padding: 8px;
  background: #1a1a1a;
}

.chat-input-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.mode-selector {
  display: flex;
  gap: 2px;
  background: #252525;
  border-radius: 6px;
  padding: 2px;
}

.mode-btn {
  background: none;
  border: none;
  border-radius: 4px;
  color: #888;
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.mode-btn:hover {
  color: #ccc;
  background: #333;
}

.mode-btn.active {
  background: #0e639c;
  color: #fff;
}

.skill-selector {
  position: relative;
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 3px 8px;
  background: #252525;
  border-radius: 6px;
  cursor: pointer;
  font-size: 11px;
  color: #aaa;
}

.skill-selector:hover {
  background: #333;
}

.skill-dropdown {
  position: absolute;
  bottom: 100%;
  left: 0;
  margin-bottom: 4px;
  background: #2d2d2d;
  border: 1px solid #444;
  border-radius: 8px;
  padding: 4px;
  min-width: 160px;
  max-height: 200px;
  overflow-y: auto;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}

.skill-option {
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 11px;
  color: #ccc;
  cursor: pointer;
}

.skill-option:hover {
  background: #3a3a3a;
}

.skill-option.selected {
  background: #1a3a5c;
  color: #7ec8e3;
}

.skill-option.neutral-hint {
  border-bottom: 1px solid #333;
  color: #999;
  font-style: italic;
}

.chat-input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  background: #252525;
  border: 1px solid #3a3a3a;
  border-radius: 10px;
  padding: 6px 10px;
  transition: border-color 0.2s;
}

.chat-input-wrapper:focus-within {
  border-color: #0e639c;
}

.chat-input-wrapper.drag-over {
  border-color: #0e639c;
  background: #1a2a3a;
}

.chat-attach-btn {
  background: none;
  border: none;
  color: #888;
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 4px;
  transition: color 0.15s, background 0.15s;
}

.chat-attach-btn:hover {
  color: #ccc;
  background: #333;
}

.chat-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: #e0e0e0;
  font-size: 13px;
  line-height: 1.4;
  resize: none;
  max-height: 120px;
  font-family: inherit;
}

.chat-input::placeholder {
  color: #666;
}

.chat-send-btn,
.chat-stop-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s;
}

.chat-send-btn {
  background: #0e639c;
  color: #fff;
}

.chat-send-btn:hover:not(:disabled) {
  background: #1177bb;
}

.chat-send-btn:disabled {
  background: #333;
  color: #666;
  cursor: not-allowed;
}

.chat-stop-btn {
  background: #a83232;
  color: #fff;
  font-size: 10px;
}

.chat-stop-btn:hover {
  background: #c43c3c;
}

/* 图片预览区 */
.image-preview-area {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  padding: 4px 2px;
  margin-bottom: 4px;
}

.image-preview-item {
  position: relative;
  width: 60px;
  height: 60px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #444;
  flex-shrink: 0;
}

.image-preview-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.image-remove-btn {
  position: absolute;
  top: 1px;
  right: 1px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.image-remove-btn:hover {
  background: rgba(168, 50, 50, 0.9);
}
</style>
