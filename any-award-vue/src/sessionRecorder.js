// 自动收集玩家侧对局记录（契约见 archive/schema.json v1）。本文件不含任何界面逻辑：
// 游戏状态每次变化自动重算记录并持久化到 localStorage（键 any-award-vue-record-v1）；
// 打通四幕后自动下载记录 JSON，交给 archive/auto_inbox.py 或 museum_writer.py deposit 入馆。
import { candidates } from './data.js';
import { meetings, people } from './content.js';

const RECORD_KEY = 'any-award-vue-record-v1';
const AWARD_NAME = '有志少年奖';
// 本地收集服务（archive/auto_inbox.py serve）；POST 成功则静默入馆，
// 服务未启动时降级为自动下载记录文件，避免记录丢失。
const INGEST_URL = 'http://127.0.0.1:8765/ingest';

function materialText(c) {
  return [
    `姓名：${c.name}`,
    `性别：${c.gender}`,
    `学院：${c.college}`,
    `专业：${c.major}`,
    `班级：${c.class}`,
    `学号：${c.student_id}`,
    `绩点：${c.gpa}/${c.gpa_scale}（${c.gpa_rank_scope}${c.gpa_rank}/${c.gpa_rank_total}）`,
    `个人陈述：${c.form.personal_statement}`,
    `科研经历：${c.form.research}`,
    `梦想档案：${c.archive.text}`,
    `梦想实现：${c.form.realization}`,
    `导师意见：${c.form.mentor_comment}　导师：${c.mentor.name}（${c.mentor.title}）`,
  ].join('\n');
}

function meetingEvents() {
  return meetings.map(([id, text]) => ({
    type: 'speech', phase: 'meeting', actor: people[id].name, text,
  }));
}

function defenseEvents(state) {
  return state.selected.map(id => {
    const c = candidates.find(x => x.id === id);
    return {
      type: 'qa', phase: 'defense', candidate: id,
      questioner: people[c.questioner]?.name || c.questioner,
      question: c.question, answer: c.answer,
    };
  });
}

// 纯函数：由当前游戏状态重建整局记录。recordStateChange 每步调用它。
export function buildRecord(state, startedAt) {
  const events = [...meetingEvents()];
  const player = state.profile.playerName || '吴主任';
  if (state.selected.length === 3) {
    events.push({ type: 'shortlist', item_ids: [...state.selected], decided_by: player });
    events.push(...defenseEvents(state));
  }
  if (state.winner) {
    const winner = candidates.find(c => c.id === state.winner);
    const decision = { type: 'decision', winner: state.winner, decided_by: player };
    if (['ceremony', 'end'].includes(state.scene) && winner?.quote) {
      decision.citation = winner.quote;
    }
    events.push(decision);
  }
  return {
    schema_version: 1,
    meta: {
      source_module: 'frontend',
      award_name: AWARD_NAME,
      played_at: startedAt,
      school_name: state.profile.schoolName || null,
      player_name: player,
    },
    participants: Object.values(people).map(p => ({ name: p.name })),
    candidates: candidates.map(c => ({
      id: c.id,
      name: c.name,
      summary: `${c.college} · ${c.major}`,
      materials: materialText(c),
    })),
    events,
    outcome: { final_order: null, shortlist: [...state.selected], winner: state.winner || null },
  };
}

function downloadRecord(record) {
  const blob = new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `any-award-session-${record.meta.played_at.slice(0, 19).replace(/[:T]/g, '-')}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function collect(record) {
  try {
    const res = await fetch(INGEST_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(record),
    });
    return res.ok;
  } catch {
    return false;
  }
}

let startedAt = null;
let restored = false;
let downloadedKey = '';

function isFresh(s) {
  return s.scene === 'chat' && s.line === 0 && !s.selected.length && !s.winner && !s.read.length;
}

// 挂到 App.vue 的 watch(state, recordStateChange, { deep: true }) 上。
export function recordStateChange(state) {
  if (typeof localStorage === 'undefined') return;
  if (!restored) {
    restored = true;
    try {
      const stored = JSON.parse(localStorage.getItem(RECORD_KEY) || 'null');
      if (stored?.meta?.played_at) startedAt = stored.meta.played_at;
    } catch {}
  }
  if (isFresh(state)) {
    startedAt = null;
    downloadedKey = '';
    try { localStorage.removeItem(RECORD_KEY); } catch {}
  }
  if (!startedAt) startedAt = new Date().toISOString();
  const record = buildRecord(state, startedAt);
  try { localStorage.setItem(RECORD_KEY, JSON.stringify(record)); } catch {}
  if (state.scene === 'end' && state.winner) {
    const key = `${state.winner}:${state.selected.join(',')}`;
    if (key !== downloadedKey) {
      downloadedKey = key;
      collect(record).then(ok => {
        if (!ok) downloadRecord(record);
      });
    }
  }
}
