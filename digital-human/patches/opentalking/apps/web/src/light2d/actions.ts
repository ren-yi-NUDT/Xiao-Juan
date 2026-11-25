/** 2D 分层讲解员的动作状态机纯函数（便于单测与复用）。 */

/** 从文本中按关键词表匹配动作 id；命中多个时取第一个命中的动作 */
export function matchAction(text: string, keywords: Record<string, string[]>): string | null {
  for (const [action, words] of Object.entries(keywords)) {
    for (const word of words) {
      if (word && text.includes(word)) return action;
    }
  }
  return null;
}

/** 中文分句：按标点切分，返回非空短句 */
export function splitSentences(text: string): string[] {
  return text
    .split(/[。！？!?；;，,、\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/** 从列表随机取一个，尽量避开 exclude */
export function pickRandom(list: string[], exclude?: string): string {
  if (list.length === 0) return "";
  if (list.length === 1) return list[0];
  let pick = list[Math.floor(Math.random() * list.length)];
  let guard = 0;
  while (pick === exclude && guard < 10) {
    pick = list[Math.floor(Math.random() * list.length)];
    guard += 1;
  }
  return pick;
}

/** 从一段回答文本里，按分句倒序找最后一个命中关键词的动作 */
export function actionForAnswer(
  text: string,
  keywords: Record<string, string[]>,
  splitOnBoundary: boolean,
): string | null {
  const cleaned = text.trim();
  if (!cleaned) return null;
  const sentences = splitOnBoundary ? splitSentences(cleaned) : [cleaned];
  for (let i = sentences.length - 1; i >= 0; i -= 1) {
    const matched = matchAction(sentences[i], keywords);
    if (matched) return matched;
  }
  return null;
}
