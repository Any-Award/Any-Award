<script setup>
import { onMounted, ref } from 'vue'

const props = defineProps({
  candidate: { type: Object, required: true },
  page: { type: Number, required: true },
  selected: { type: Boolean, required: true },
  selectedCount: { type: Number, required: true },
  review: { type: Boolean, required: true },
  school: { type: String, default: '本校' },
  player: { type: String, default: '吴主任' },
})
const emit = defineEmits(['close', 'flip'])
const paper = ref(null)

function handleKey(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    emit('close')
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    event.stopPropagation()
    emit('flip')
  }
}

onMounted(() => paper.value?.focus({ preventScroll: true }))
</script>

<template>
  <section
    class="overlay-back"
    role="dialog"
    aria-modal="true"
    :aria-label="`${candidate.name}报名表详情`"
    @keydown="handleKey"
  >
    <article
      id="expanded-form"
      ref="paper"
      class="paper form-paper"
      :class="{ 'back-page': page !== 0 }"
      tabindex="0"
      aria-label="双击收回报名表"
      @dblclick.prevent="emit('close')"
    >
      <template v-if="page === 0">
        <div class="form-top">
          <span>附表一　／　{{ props.school || '本校' }}</span>
          <span>{{ candidate.id }}　正面</span>
        </div>
        <h2>有志少年奖报名表</h2>
        <div class="docno">2026年度试点 · 2016年志向档案</div>
        <table>
          <tbody>
            <tr><th>姓名</th><td>{{ candidate.name }}</td><th>性别</th><td>{{ candidate.gender }}</td></tr>
            <tr><th>入学年份</th><td>{{ candidate.enroll_year }}</td><th>学院</th><td>{{ candidate.college }}</td></tr>
            <tr><th>专业</th><td>{{ candidate.major }}</td><th>班级</th><td>{{ candidate.class }}</td></tr>
            <tr><th>学号</th><td>{{ candidate.student_id }}</td><th>绩点</th><td>{{ candidate.gpa }}/{{ candidate.gpa_scale }}</td></tr>
            <tr><th>排名</th><td colspan="3">{{ candidate.gpa_rank_scope }} {{ candidate.gpa_rank }}/{{ candidate.gpa_rank_total }}</td></tr>
            <tr><th>个人陈述</th><td colspan="3">{{ candidate.form.personal_statement }}</td></tr>
            <tr><th>科研经历</th><td colspan="3">{{ candidate.form.research }}</td></tr>
            <tr class="archive"><th>梦想档案</th><td colspan="3">{{ candidate.archive.text }}</td></tr>
            <tr><th>实现情况</th><td colspan="3">{{ candidate.form.realization }}</td></tr>
            <tr><th>导师意见</th><td colspan="3">{{ candidate.form.mentor_comment }}　导师：{{ candidate.mentor.name }}</td></tr>
            <tr><th>签章</th><td colspan="3">学生签字：________　导师签字：________</td></tr>
          </tbody>
        </table>
        <div class="notes">
          身份信息由系统调档。梦想档案为2016年归档原文，不可修改。<br>
          补充说明及委员审查记录见背面。
        </div>
      </template>
      <template v-else>
        <div class="form-top"><span>附表一　／　委员留存</span><span>{{ candidate.id }}　背面</span></div>
        <h2>补充说明与审查记录</h2>
        <p>学生补充说明：{{ candidate.form.supplement || '无' }}</p>
        <p>联系电话：{{ candidate.phone }}<br>邮箱：{{ candidate.email }}</p>
        <p>材料核对：身份栏、原始档案、本人陈述、导师意见。</p>
        <div class="handnote">{{ selected ? '已列入答辩名单。' : '待审阅。' }}</div>
        <div class="writing-lines" aria-hidden="true"><i v-for="line in 6" :key="line"></i></div>
        <div class="signoff">委员签字：{{ props.player || '吴主任' }}<br>2026年6月</div>
      </template>
    </article>
    <aside class="form-controls">
      <div class="eyebrow">报名材料　／　{{ page ? '背面' : '正面' }}</div>
      <h2>{{ candidate.name }}</h2>
      <p>{{ candidate.college }}<br>{{ candidate.major }}</p>
      <p>双击左侧报名表，<br>缩小并放回桌面原处。<br><small>也可按Esc收回，方向键翻面。</small></p>
      <div class="actions">
        <button type="button" class="small" data-action="flip" @click="emit('flip')">{{ page ? '查看正面' : '翻看背面' }}</button>
        <button type="button" class="small" data-action="close-form" @click="emit('close')">收回报名表</button>
      </div>
      <template v-if="review">
        <p>答辩名额：{{ selectedCount }}/3</p>
        <p>{{ selected ? '当前位于右侧入围区。' : '当前位于左侧待审区。' }}<br>收回材料后拖动卡片，调整入围名单。</p>
      </template>
      <p v-else>材料只读，供现场复核。</p>
    </aside>
  </section>
</template>
