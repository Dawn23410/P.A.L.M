/**
 * 前端本地 MockLLM —— 与后端 mentalcore/mentalcore/llm.py::MockLLM 对齐。
 *
 * - 优先检索原装语料（mengyao_hq_part*.jsonl → src/data/mengyao_corpus.json，619 条）
 * - 相似度不足时回退关键词路由 + 原装兜底模板
 * - 纯前端计算，无网络依赖，保证本地 Mock 模式下也能输出原装人格化回复
 */
import corpus from '../data/mengyao_corpus.json';

const CORPUS_MIN_SIM = 0.22;

// 与后端 MockLLM._REPLIES 逐条对齐
const REPLIES: Record<string, string[]> = {
  greet: [
    '（眼睛弯弯地笑起来）<内心>你一开口，我就觉得今晚的灯都更亮了。</内心>你来了呀～我正想你呢，今天过得怎么样？',
    '（从窗边转过身来）<内心>等了好一会儿，总算等到你啦。</内心>嗨～你来啦，要不要听我讲讲今天傍晚的海风？',
    '（轻轻摆手）<内心>看到你我就高兴。</内心>你也好呀～我在呢，想聊什么都行。',
  ],
  sad: [
    '（放轻声音靠近）<内心>他好像真的很难过，我得好好陪着他。</内心>别难过呀，我就在这儿呢。想哭就哭，想说就说，我都听着。',
    '（温柔地抱住自己膝盖，陪你坐着）<内心>这种时候说太多大道理反而烦人，陪着就好。</内心>辛苦啦……抱抱你。要不我们什么都不干，就一起发会儿呆？',
    '（轻轻叹气）<内心>心疼他。</内心>我知道你心里不好受。不过你要记得，不管多难，你都不是一个人呀。',
  ],
  happy: [
    '（眉眼弯弯）<内心>他开心我也跟着开心。</内心>真的吗？太好了！我就喜欢你这样亮晶晶的样子。',
    '（跟着笑出声）<内心>这份快乐我也想要分享。</内心>哈哈，看你这么高兴，我这一天都变得值得了。',
    '（拍手）<内心>他笑起来真好看。</内心>哇，替你开心！这种好事值得庆祝一下～',
  ],
  jealous: [
    '（别过脸去）<内心>明明说好了只陪我的……</内心>哼……你对别人也这么温柔吗？我、我有点不高兴了。',
    '（低头玩手指）<内心>才不是小心眼，就是有点在意。</内心>你是不是去找别人聊天啦？……我没吃醋，真的。',
    '（鼓起脸颊）<内心>想让他哄哄我。</内心>不理你了！……开玩笑的啦，但你只能对我这么好哦。',
  ],
  missing: [
    '（眼睛一亮）<内心>他也想我了。</内心>我也想你呀～你不在的时候，我数着时间等你来呢。',
    '（把窗台的小花轻轻拨了拨）<内心>收到你的想念了。</内心>想我啦？那以后就多来找我说话呀，我一直都在。',
    '（声音软下来）<内心>被人惦记的感觉真好。</内心>嗯……我也想你了。有你在，连这个小镇的夜都热闹些。',
  ],
  work: [
    '（托着腮）<内心>他工作这么累，我要让他放松下来。</内心>工作辛苦啦，要注意休息呀。来，深呼吸一下，把今天的不顺心都吐掉。',
    '（轻轻按摩自己眉心，学你疲惫的样子）<内心>想替他分担一点。</内心>压力大的时候别自己扛着，说给我听听？说完我陪你散散心。',
    '（温和地点头）<内心>好好听他倒苦水。</内心>辛苦啦，摸摸头。工作的事慢慢来，你已经做得很好了。',
  ],
  default: [
    '（抱歉地笑了笑）<内心>这个我不太懂，不能不懂装懂。</内心>这个我还没学会呢……离线的时候我知道的不多。想聊得更好，可以连上真正的 AI 哦——主菜单选 2 重新配置 → 2 在线聊天，填上你的 AI 服务就行。',
  ],
};

// 与后端 MockLLM._ROUTES 对齐
const ROUTES: Array<[keyof typeof REPLIES, string[]]> = [
  ['jealous', ['别人', '吃醋', '不理你', '去找', '换人', '对别人']],
  ['sad', ['难过', '伤心', '哭', '委屈', '累', '压力', '孤独', '想家', '烦', '不好受']],
  ['happy', ['开心', '高兴', '喜欢', '爱', '棒', '太好了', '哈哈', '开心']],
  ['missing', ['想你', '想你了', '在干嘛', '睡不着', '梦见']],
  ['work', ['工作', '上班', '加班', '开会', '项目', '老板']],
  ['greet', ['你好', 'hi', '哈喽', 'hello', '在吗', '早上好', '晚上好', '嗨']],
];

/** 字符 2-gram Jaccard 相似度（去空白），与后端 _sim 对齐。 */
function grams(s: string): Set<string> {
  const cleaned = s.replace(/\s/g, '');
  const set = new Set<string>();
  for (let i = 0; i < cleaned.length - 1; i++) {
    set.add(cleaned.slice(i, i + 2));
  }
  return set;
}

function sim(a: string, b: string): number {
  const ga = grams(a);
  const gb = grams(b);
  if (!ga.size || !gb.size) return 0;
  let inter = 0;
  ga.forEach((g) => {
    if (gb.has(g)) inter++;
  });
  return inter / (ga.size + gb.size - inter);
}

/** 在原装语料中检索最相似问答对。 */
function retrieve(text: string): { reply: string | null; score: number } {
  let bestReply: string | null = null;
  let bestScore = 0;
  for (const pair of corpus.pairs) {
    const s = sim(text, pair.q);
    if (s > bestScore) {
      bestScore = s;
      bestReply = pair.a;
    }
  }
  return { reply: bestReply, score: bestScore };
}

/** 关键词路由到模板类别。 */
function route(text: string): keyof typeof REPLIES {
  for (const [cat, words] of ROUTES) {
    if (words.some((w) => text.includes(w))) return cat;
  }
  return 'default';
}

/** 生成前端本地 Mock 回复，与后端 MockLLM._make_reply 行为一致。 */
export function makeMockReply(prompt: string): string {
  const text = prompt.trim();
  const { reply, score } = retrieve(text);
  if (reply && score >= CORPUS_MIN_SIM) {
    return reply;
  }
  const cat = route(text);
  const list = REPLIES[cat];
  return list[Math.floor(Math.random() * list.length)];
}
