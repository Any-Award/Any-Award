<script setup>
import { people,image } from '../content.js';import DialogueBox from './DialogueBox.vue';
defineProps({candidate:Object,school:String,player:String});defineEmits(['handover']);
</script>
<template><div class="scene-tag">第四幕　／　有志少年奖颁奖典礼</div><div class="placeholder-note">典礼背景待补 · 学生立绘为通用占位</div><div class="certificate"><h2>荣誉证书</h2><p>{{ candidate.name }}同学<br>荣获2026年度<br>“有志少年奖”</p><div class="stamp">{{ school }}<br>奖委会</div></div><div class="stage-floor"></div><img :src="image('whole_demogirl')" class="student" alt="获奖者临时占位立绘" draggable="false"><img :src="image(people.guo.whole)" class="defense-committee" alt="郭校长" draggable="false"><DialogueBox speaker="主持人" :text="candidate.quote+'下面有请'+player+'为获奖同学颁奖。'"><button class="primary" data-action="handover" @click="$emit('handover')">递过荣誉证书</button></DialogueBox></template>
