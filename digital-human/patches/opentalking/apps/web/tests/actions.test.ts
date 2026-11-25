import assert from "node:assert/strict";
import test from "node:test";

import { actionForAnswer, matchAction, pickRandom, splitSentences } from "../src/light2d/actions";

const KEYWORDS: Record<string, string[]> = {
  speak_point: ["请看", "这边", "位于", "前方"],
  speak_welcome: ["欢迎", "大家好"],
  speak_emphasize: ["重点", "注意", "一定"],
  speak_think: ["据说", "相传"],
  speak_measure: ["高达", "米", "吨"],
  speak_nod: ["对的", "没错"],
};

test("splitSentences 按中文标点切分并去空", () => {
  assert.deepEqual(splitSentences("灵山大佛高达88米，请看这边。"), ["灵山大佛高达88米", "请看这边"]);
  assert.deepEqual(splitSentences("  hello!  世界？"), ["hello", "世界"]);
});

test("matchAction 命中关键词返回动作，未命中返回 null", () => {
  assert.equal(matchAction("欢迎来到灵山", KEYWORDS), "speak_welcome");
  assert.equal(matchAction("没有关键词", KEYWORDS), null);
});

test("actionForAnswer 取最后一个分句的命中动作", () => {
  // 第一句"欢迎"、第二句"请看这边"，应取最后命中的 speak_point
  assert.equal(actionForAnswer("欢迎大家。请看这边的高塔。", KEYWORDS, true), "speak_point");
  // 单句模式扫全文
  assert.equal(actionForAnswer("灵山大佛高达88米", KEYWORDS, false), "speak_measure");
  // 不命中返回 null（由调用方随机 fallback）
  assert.equal(actionForAnswer("今天天气不错", KEYWORDS, true), null);
});

test("pickRandom 只从列表取，且尽量避开 exclude", () => {
  const list = ["a", "b", "c"];
  assert.ok(list.includes(pickRandom(list)));
  assert.equal(pickRandom(["only"]), "only");
  assert.equal(pickRandom([]), "");
  for (let i = 0; i < 20; i += 1) {
    assert.notEqual(pickRandom(list, "a"), "a");
  }
});
