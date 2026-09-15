import cn2an
import re
from rapidfuzz import fuzz

class ExhibitIntentMatcher:
    def __init__(self, config):
        """
        初始化匹配引擎
        :param config: 包含展区配置的字典 (结构见下文)
        """
        self.area_name = config.get("area_name", "Unknown Area")
        self.global_excludes = config.get("global_excludes", [])
        self.products = config.get("products", [])

        # 性能参数：模糊匹配阈值 (0-100)
        self.match_threshold = config.get("settings", {}).get("fuzzy_threshold", 60)

    def _normalize(self, text):
        """
        文本归一化：中文数字转阿拉伯数字 -> 转大写 -> 去空格
        """
        if not text:
            return ""
        try:
            # 模式: "smart" 可以同时处理 "一二三" 和 "一百二十三"
            text = cn2an.transform(text, "cn2an")
        except:
            pass
        return text.upper().replace(" ", "")

    def predict(self, user_query):
        """
        核心预测接口
        :param user_query: 用户原始语音文本
        :return: { "success": bool, "product_id": str, "score": int, "debug_info": str }
        """
        norm_query = self._normalize(user_query)

        # 1. 【全局卫士】检查是否命中全局黑名单 (如本展区没有的 )
        for neg_word in self.global_excludes:
            # 排除词建议用原始文本匹配，防止归一化丢失语义
            if neg_word in user_query or neg_word in norm_query:
                return {
                    "success": False,
                    "product_id": None,
                    "reason": f"Hit global exclude: {neg_word}"
                }

        candidates = []

        # 2. 【产品遍历】
        for product in self.products:
            p_id = product["id"]

            # A. 产品级黑名单检查
            hit_exclude = False
            for exc in product.get("exclude_words", []):
                if exc in user_query or exc in norm_query:
                    hit_exclude = True
                    break
            if hit_exclude:
                continue

            # B. 【强特征锚点检查】 (Must-Have Logic)
            # 这是一个硬性过滤器：如果定义了 anchors，则必须命中至少一个
            anchors = product.get("anchors", [])
            anchor_hit = False

            if not anchors:
                # 如果没定义锚点，说明该产品允许仅通过名称模糊匹配 (通常不建议)
                anchor_hit = True
            else:
                for anchor in anchors:
                    norm_anchor = self._normalize(anchor)
                    if norm_anchor in norm_query:
                        anchor_hit = True
                        break

            if not anchor_hit:
                continue

            # C. 【评分机制】
            # 如果通过了强特征检查，计算名称相似度作为最终得分
            # 取该产品所有别名中，与用户输入最相似的那个分数
            best_name_score = 0
            for name in product["names"]:
                norm_name = self._normalize(name)
                # partial_ratio 适合长句包含短词的情况
                score = fuzz.partial_ratio(norm_name, norm_query)
                if score > best_name_score:
                    best_name_score = score

            # 记录候选项
            if best_name_score >= self.match_threshold:
                candidates.append({
                    "id": p_id,
                    "score": best_name_score,
                    "matched_anchor": anchors
                })

        # 3. 【择优录取】
        if not candidates:
            return {
                "success": False,
                "product_id": None,
                "reason": "No anchors matched or score too low"
            }

        # 按分数降序排列，如果分数一样，优先选 ID 较长的 (通常 ID 长意味着更具体)
        candidates.sort(key=lambda x: (x["score"], len(x["id"])), reverse=True)

        best_candidate = candidates[0]

        # return best_candidate["id"]
        return {
            "success": True,
            "product_id": best_candidate["id"],
            "score": best_candidate["score"],
            "reason": "Matched"
        }