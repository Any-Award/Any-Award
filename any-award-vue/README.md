# 《颁什么奖》有志少年奖 · Vue 3版

这是原HTML原型的Vue组件化重写，不是Vue外壳包旧页面。使用Vue 3 Composition API、单文件组件、props/emits和响应式状态，不使用innerHTML/v-html替换游戏页面。固定剧本，无AI、后端或CDN。

## 直接运行

打开[dist/index.html](<dist/index.html>)即可离线游玩。Vue运行时、数据、图片和字体全部随包提供，无需Node、npm、服务器或网络。复制整个dist文件夹即可换机器运行。

根目录index.html是Vite开发入口，不能直接双击运行；请打开dist内入口。

## 开发

Node.js 20.19+或22.12+（已使用Node 24验证）。首次安装开发依赖需要包源访问；安装后可本地开发。

```sh
npm ci
npm run dev
npm run build
```

构建先由Vite编译Vue SFC，生成单个IIFE，再把入口调整为经典defer脚本，使file://下可直接运行。没有动态模块加载或外部Vue引用。npm run preview也可预览，但正常游玩不需要启动它。

## 功能保持

- 1920×1080等比缩放；第一幕群聊与会议讨论结束直接收表，无表态/投票/签发确认页。
- 第二幕4张姓名/院系卡片，2:1待审区/入围区；拖入右侧入围，拖回左侧取消，卡片中心为判据。恰好3人可提交。
- 双击展开A4详情，再次双击收回原位；翻面、Esc、方向键均可操作。
- 第三幕每人一位委员一问一答，最后选1人获奖；第四幕递证书结束。
- 名称设置、本地存档、重新开始、全屏。
- 原画从assets_png原样带入，不改色、不叠加效果。思源黑体Regular随包；公文/证书采用系统宋体，无宋体时回退serif。
- 答辩和颁奖背景仍占位；whole_demogirl仍为通用占位立绘。

Vue版使用独立存档键any-award-vue-v1，不自动导入旧HTML存档。存档属于浏览器，不随复制文件夹迁移；禁用存储时仍可玩但不续存。

## 结构

- [src/App.vue](<src/App.vue>)：页面外壳、场景组合与弹窗。
- [src/useAward.js](<src/useAward.js>)：状态、流程、名单规则、存档校验与生命周期监听。
- [src/data.js](<src/data.js>)：候选人事实、固定材料和答辩；未来可替换为独立内容适配器。
- [src/content.js](<src/content.js>)：委员、会议台词及图片路径。
- src/components：ChatScene、MeetingScene、ReviewDesk、CandidateForm、DefenseScene、DecisionScene、CeremonyScene、EndScene和DialogueBox。
- public/assets：原画与字体；项目外无运行文件依赖。
- [scripts/offline.mjs](<scripts/offline.mjs>)：生成file://兼容入口。
- [scripts/test-browser.cjs](<scripts/test-browser.cjs>)：真实Edge DevTools浏览器回归测试（开发验证，非游玩依赖）。

测试脚本需先启动远程调试端口9331的测试浏览器，再执行node scripts/test-browser.cjs。可用AWARD_TEST_ENTRY指定异地解压后的dist/index.html。脚本会重置测试页面本地存档并关闭测试浏览器。

## 验证范围

已实际验证离线file://运行、字体图片加载、无投票跳转、四幕全流程、真实指针拖入/拖出、4人时禁止提交、整理保持名单、4份A4无溢出、双击位置不变、单问答、获奖一致、名称设置、刷新保存、1280×720缩放拖动、无JS异常和无网络请求。

未附带node_modules；源码包带package-lock.json以便npm ci安装。运行包只包含dist内容，无开发工具和浏览器缓存。
