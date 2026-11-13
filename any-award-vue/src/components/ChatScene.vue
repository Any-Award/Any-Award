<script setup>
import { people, image } from '../content.js';
defineProps({ player: String });
defineEmits(['receive']);
const members=['guo','zhao','qian','sun','li','zhou'];
</script>
<template><div class="chat-layout"><aside class="chat-intro"><div class="eyebrow">第一幕　／　会议通知</div><div class="time">08:00</div><h1 class="section-title">只差你了。</h1><p>星期一。<br>办公室电脑上的工作群，<br>又跳出一条通知。</p><p>你是{{ player }}。<br>奖励执行委员会组长。</p></aside><section class="chat-panel"><div class="chat-title"><span>奖励执行委员会（7人）</span><span>工作群</span></div><div class="messages"><div v-for="(id,i) in members" :key="id" class="message"><img class="avatar" :src="image(people[id].thumb)" :alt="people[id].name" draggable="false"><div class="message-content"><div class="message-name">{{ people[id].name }}　08:00</div><div class="bubble">{{ i===0?'@所有人 请奖励执行委员会全体成员参加会议，地点308会议室，会议时间12:00—14:00，若无特殊情况务必全体到会！':'收到' }}</div></div></div></div><div class="chat-send"><span>五条“收到”之后，消息停住了。</span><button class="primary" data-action="received" @click="$emit('receive')">收到 →</button></div></section></div></template>
