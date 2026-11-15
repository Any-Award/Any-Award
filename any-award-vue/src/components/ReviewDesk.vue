<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  candidates: { type: Array, required: true },
  positions: { type: Object, required: true },
  selected: { type: Array, required: true },
  scale: { type: Number, required: true },
})
const emit = defineEmits(['move', 'front', 'drop', 'open', 'tidy', 'submit'])
const drag = ref(null)
const suppressDoubleUntil = ref(0)
const selectedNames = computed(() => props.selected
  .map(id => props.candidates.find(candidate => candidate.id === id)?.name)
  .filter(Boolean).join('、') || '尚未批定')

function startDrag(event, id) {
  if (event.button !== 0 || drag.value || event.isPrimary === false) return
  const position = props.positions[id]
  const card = event.currentTarget
  drag.value = {
    id, card, pointerId: event.pointerId,
    startX: event.clientX, startY: event.clientY,
    x: position.x, y: position.y, moved: false,
  }
  card.focus({ preventScroll: true })
  card.setPointerCapture(event.pointerId)
  emit('front', id)
}

function moveDrag(event) {
  const current = drag.value
  if (!current || event.pointerId !== current.pointerId) return
  const scale = Number.isFinite(props.scale) && props.scale > 0 ? props.scale : 1
  const dx = (event.clientX - current.startX) / scale
  const dy = (event.clientY - current.startY) / scale
  if (!current.moved && Math.hypot(dx, dy) < 6) return
  event.preventDefault()
  current.moved = true
  emit('move', {
    id: current.id,
    x: Math.max(20, Math.min(1490, current.x + dx)),
    y: Math.max(20, Math.min(400, current.y + dy)),
  })
}

function finishDrag(event, cancel = false) {
  const current = drag.value
  if (!current || (event && event.pointerId !== current.pointerId)) return
  // Clear before releasing capture: lostpointercapture must not finish twice.
  drag.value = null
  if (current.moved) suppressDoubleUntil.value = Date.now() + 350
  if (cancel) emit('move', { id: current.id, x: current.x, y: current.y })
  if (current.card.hasPointerCapture(current.pointerId)) {
    current.card.releasePointerCapture(current.pointerId)
  }
  // The parent owns the centre-based 1190 divider and shortlist updates.
  emit('drop')
}

function openCard(id) {
  if (drag.value || Date.now() < suppressDoubleUntil.value) return
  emit('open', id)
}

function openWithKeyboard(event, id) {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  if (!event.repeat) openCard(id)
}

onBeforeUnmount(() => {
  const current = drag.value
  drag.value = null
  if (current?.card.hasPointerCapture(current.pointerId)) {
    current.card.releasePointerCapture(current.pointerId)
  }
})
</script>

<template>
  <div class="desk-head">
    <div>
      <div class="eyebrow">第二幕　／　报名材料审阅</div>
      <h1 class="section-title">四份材料，三个名额。</h1>
      <p>拖到右侧即入围，拖回左侧即取消。双击查看，再次双击收回。</p>
    </div>
    <div class="subtitle">评选依据<br>实际学习或活动与童年志向相关即可。</div>
  </div>
  <div id="desk" class="desk">
    <div class="review-zone"><span>待审区</span></div>
    <div class="shortlist-zone"><span>入围区</span><small>将材料拖入此处</small></div>
    <i class="desk-line" aria-hidden="true"></i>
    <i class="desk-line second" aria-hidden="true"></i>
    <div
      v-for="candidate in candidates"
      :key="candidate.id"
      class="file-card"
      role="button"
      tabindex="0"
      :data-card="candidate.id"
      :aria-label="`${candidate.name}，${candidate.college}，双击查看报名表`"
      :style="{
        left: `${positions[candidate.id].x}px`,
        top: `${positions[candidate.id].y}px`,
        zIndex: positions[candidate.id].z,
        transform: `rotate(${positions[candidate.id].r}deg)`,
      }"
      @pointerdown="startDrag($event, candidate.id)"
      @pointermove="moveDrag"
      @pointerup="finishDrag($event)"
      @pointercancel="finishDrag($event, true)"
      @lostpointercapture="finishDrag($event, true)"
      @dblclick.prevent="openCard(candidate.id)"
      @keydown="openWithKeyboard($event, candidate.id)"
      @dragstart.prevent
    >
      <strong>{{ candidate.name }}</strong>
      <span>{{ candidate.college }}</span>
    </div>
  </div>
  <div class="desk-bottom">
    <div class="selection-text">
      答辩名单（{{ selected.length }}/3）：{{ selectedNames }}<br>
      <small>以卡片中心落点判定分区；选定3人后提交答辩名单。</small>
    </div>
    <div class="desk-tools">
      <button type="button" data-action="tidy" @click="emit('tidy')">整理桌面</button>
      <button type="button" data-action="start-defense" class="primary" :disabled="selected.length !== 3" @click="emit('submit')">
        提交名单，进入答辩 →
      </button>
    </div>
  </div>
</template>

<style scoped>
.file-card {
  touch-action: none;
  user-select: none;
}
</style>
