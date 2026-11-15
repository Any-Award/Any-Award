export const people={guo:{name:'郭校长',whole:'whole_guoxiaozhang',thumb:'thumbnail_guoxiaozhang'},zhao:{name:'赵副主任',whole:'whole_zhaofuzhuren',thumb:'thumbnail_zhaofuzhuren'},qian:{name:'钱教授',whole:'whole_quanjiaoshou',thumb:'thumbnail_qianjiaoshou'},sun:{name:'孙处长',whole:'whole_sunchuzhang',thumb:'thumbnail_sunchuzhang'},li:{name:'李部长',whole:'whole_libuzhang',thumb:'thumbnail_libuzhang'},zhou:{name:'周处长',whole:'whole_zhouchuzhang',thumb:'thumbnail_zhouchuzhang'}};
export const meetings=[
 ['guo','同志们，十年前，我们请一群孩子写下了自己的梦想。那些档案一直留着。如今他们中有人已经来到我们学校，即将毕业。'],
 ['guo','我想在任期结束前，借这份档案办一次“有志少年奖”。看看十年前的那句话，如今走到了什么地方。'],
 ['zhao','有原始档案，程序上就有依据。评选条件、报名材料与最终名单，都应当完整留存。'],
 ['qian','我赞成看实际做过什么。专业名称和实际工作，要分开核对。不能因为说得好，就当作做到了。'],
 ['sun','孩子们会变，愿望也会变。通知里写明自愿申报，也别把没获奖说成“初心不合格”。'],
 ['li','十年之约，确实有传播价值。不过怎么介绍学生，最好也听听他们自己的意思。'],
 ['zhou','试点规模先控制好。材料、签发稿、证书都要对得上，最后由吴主任汇总裁定。我讲清楚了吗？'],
 ['guo','讨论就到这里。按实际学习或活动与童年志向的联系来审阅，不要求严格实现。吴主任，接下来请收取报名材料。']
];
export const image = file => `./assets/${file === "meeting_room" ? "places" : "people"}/${file}.png`;
