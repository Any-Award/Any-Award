import { reactive, ref, computed, watch, onMounted, onUnmounted } from 'vue';
import { candidates } from './data.js';
import { meetings } from './content.js';
const KEY='any-award-vue-v1';
const scenes=['chat','meeting','review','defense','decision','ceremony','end'];
const initialPosition=i=>[{x:130,y:120,z:1,r:-6},{x:510,y:220,z:2,r:5},{x:750,y:75,z:3,r:-3},{x:180,y:350,z:4,r:7}][i];
const fresh=()=>({scene:'chat',line:0,selected:[],read:[],defenseIndex:0,defenseStep:0,winner:'',positions:Object.fromEntries(candidates.map((c,i)=>[c.id,{...initialPosition(i)}])),z:4,profile:{playerName:'吴主任',schoolName:''}});
function load(){try{const x=JSON.parse(localStorage.getItem(KEY));if(!x||!scenes.includes(x.scene))return fresh();const s=fresh();s.scene=x.scene;s.line=Math.max(0,Math.min(meetings.length-1,Number(x.line)||0));s.profile={playerName:typeof x.profile?.playerName==='string'?x.profile.playerName.slice(0,16):'吴主任',schoolName:typeof x.profile?.schoolName==='string'?x.profile.schoolName.slice(0,24):''};for(const c of candidates){const p=x.positions?.[c.id];if(p&&Number.isFinite(p.x)&&Number.isFinite(p.y)){s.positions[c.id]={x:Math.max(20,Math.min(1490,p.x)),y:Math.max(20,Math.min(400,p.y)),r:Number.isFinite(p.r)?p.r:0,z:Number.isFinite(p.z)?p.z:1};}}s.z=Math.max(4,...Object.values(s.positions).map(p=>p.z));s.selected=candidates.filter(c=>s.positions[c.id].x+133>=1190).map(c=>c.id);s.read=Array.isArray(x.read)?x.read.filter(id=>candidates.some(c=>c.id===id)):[];s.defenseIndex=Math.max(0,Math.min(2,Number(x.defenseIndex)||0));s.defenseStep=x.defenseStep===1?1:0;s.winner=s.selected.includes(x.winner)?x.winner:'';if(['defense','decision','ceremony','end'].includes(s.scene)&&s.selected.length!==3)s.scene='review';if(['ceremony','end'].includes(s.scene)&&!s.winner)s.scene='decision';return s;}catch{return fresh();}}
export function useAward(){
 const state=reactive(load()),opened=ref(null),page=ref(0),modal=ref(''),scale=ref(1),draft=reactive({playerName:'',schoolName:''});
 const player=computed(()=>state.profile.playerName||'吴主任'),school=computed(()=>state.profile.schoolName||'本校');
 const person=id=>candidates.find(c=>c.id===id);
 const selectedCandidates=computed(()=>state.selected.map(person).filter(Boolean));
 const current=computed(()=>person(state.selected[state.defenseIndex]));
 const winner=computed(()=>person(state.winner));
 const openedCandidate=computed(()=>person(opened.value));
 const act=computed(()=>state.scene==='review'?1:['defense','decision'].includes(state.scene)?2:['ceremony','end'].includes(state.scene)?3:0);
 const text=t=>String(t).replaceAll('吴主任',player.value);
 function go(scene){state.scene=scene;opened.value=null;modal.value='';}
 function advance(){if(state.line<meetings.length-1)state.line++;else go('review');}
 function receive(){state.line=0;go('meeting');}
 function openForm(id){if(!person(id))return;opened.value=id;page.value=0;if(!state.read.includes(id))state.read.push(id);}
 function front(id){state.positions[id].z=++state.z;}
 function move({id,x,y}){Object.assign(state.positions[id],{x,y});}
 function drop(){state.selected=candidates.filter(c=>state.positions[c.id].x+133>=1190).map(c=>c.id);if(!state.selected.includes(state.winner))state.winner='';}
 function tidy(){let left=0,right=0;for(const c of candidates)state.positions[c.id]=state.selected.includes(c.id)?{x:1340,y:60+right++*155,r:0,z:++state.z}:{...initialPosition(left++),z:++state.z};}
 function startDefense(){if(state.selected.length!==3)return;state.defenseIndex=0;state.defenseStep=0;state.winner='';go('defense');}
 function answer(){state.defenseStep=1;}
 function nextCandidate(){if(state.defenseStep!==1)return;if(state.defenseIndex<2){state.defenseIndex++;state.defenseStep=0;}else go('decision');}
 function chooseWinner(id){if(state.selected.includes(id))state.winner=id;}
 function confirmWinner(){if(state.selected.includes(state.winner))go('ceremony');}
 function settings(){opened.value=null;Object.assign(draft,state.profile);modal.value='settings';}
 function saveSettings(){state.profile={playerName:draft.playerName.trim().slice(0,16)||'吴主任',schoolName:draft.schoolName.trim().slice(0,24)};modal.value='';}
 function reset(){Object.assign(state,fresh());opened.value=null;modal.value='';}
 function keydown(e){if(e.key==='Escape'){opened.value=null;modal.value='';}if(opened.value&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();page.value=1-page.value;}}
 function resize(){scale.value=Math.min(innerWidth/1920,innerHeight/1080);}
 async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{}}
 watch(state,()=>{try{localStorage.setItem(KEY,JSON.stringify(state));}catch{}},{deep:true,flush:'sync'});
 onMounted(()=>{resize();window.addEventListener('resize',resize);window.addEventListener('keydown',keydown);});
 onUnmounted(()=>{window.removeEventListener('resize',resize);window.removeEventListener('keydown',keydown);});
 return {state,opened,page,modal,scale,draft,player,school,candidates,selectedCandidates,current,winner,openedCandidate,act,text,go,advance,receive,openForm,front,move,drop,tidy,startDefense,answer,nextCandidate,chooseWinner,confirmWinner,settings,saveSettings,reset,fullscreen};
}
