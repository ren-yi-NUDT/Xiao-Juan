import openai
import time
import re
import os
import json
import torch
from prompts.chat_exec import (
    SYSTEM_PROMPT0,
    SYSTEM_PROMPT1,
    SYSTEM_PROMPT3,
    SYSTEM_PROMPT4,
    SYSTEM_PROMPT_DATABASE,
    USER_PROMPT_DATABASE,
    SYSTEM_PROMPT_LANDMARK_NAV,
)
from collections import OrderedDict
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
LLM_API_BASE = "http://192.168.3.11:8088/v1"
EMBED_MODEL_PATH = "/home/igraperobot3/Model/BAAI/bge-large-zh-v1.5"
MAX_HISTORY_ROUNDS = 10
DB_FILE_PATH = "/home/igraperobot3/Model/BAAI/museum.txt"
VECTOR_DB_PATH = "/home/igraperobot3/Model/vector_database_faiss/"
class KnowledgeBase:
    def __init__(self, device="cuda", model_name=EMBED_MODEL_PATH):
        print(f"Initializing embedding model from local path: {model_name}...")

        if not os.path.isdir(model_name):
            raise FileNotFoundError(
                f"Local model directory not found at '{model_name}'. "
                f"Please ensure the 'BAAI/bge-large-zh-v1.5' folder is in the project root."
            )

        if device == "cuda" and not torch.cuda.is_available():
            print("Warning: CUDA was requested, but CUDA is not available. Switching to cpu.")
            device = "cpu"

        self.embedding_model = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device, "local_files_only": True},
            encode_kwargs={"normalize_embeddings": True},
        )
        print("Embedding model loaded successfully.")

    def build_vector_db(self, file_path: str):
        print(f"\nBuilding new vector database from source: {file_path}...")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text_content = f.read()
        except FileNotFoundError:
            print(f"Error: Source file '{file_path}' not found.")
            return None

        final_splits = []
        exhibit_blocks = text_content.split("\n\n")
        for block in exhibit_blocks:
            block = block.strip()
            if not block:
                continue
            parent_paragraph = block
            parts = block.split("\n", 1)
            body = parts[1] if len(parts) == 2 else parts[0]
            sentences = [s.strip() for s in re.split(r"(。)", body) if s.strip()]
            combined_sentences = []
            for i in range(0, len(sentences), 2):
                sentence = sentences[i]
                if i + 1 < len(sentences):
                    sentence += sentences[i + 1]
                if sentence:
                    combined_sentences.append(sentence)
            for sentence in combined_sentences:
                new_doc = Document(page_content=sentence, metadata={"parent_paragraph": parent_paragraph})
                final_splits.append(new_doc)

        if not final_splits:
            print("Error: No text chunks were generated. Please check the source file format.")
            return None

        print(f"Created {len(final_splits)} sentence chunks. Building FAISS index...")
        start_time = time.time()
        vector_db = FAISS.from_documents(final_splits, self.embedding_model)
        end_time = time.time()
        print(f"Vector database construction completed in {end_time - start_time:.2f} seconds.")
        return vector_db

class LLM_ASSISTENT:
    def __init__(self, api_base=LLM_API_BASE, embed_model_path=EMBED_MODEL_PATH,
                 db_file_path=DB_FILE_PATH, vector_db_path=VECTOR_DB_PATH):
        def _build_vector_db():
            vector_database = None
            kb_builder = KnowledgeBase(device="cuda", model_name=embed_model_path)
            if os.path.exists(vector_db_path):
                print(f"Found existing vector database at '{vector_db_path}'. Loading...")
                start_time = time.time()
                vector_database = FAISS.load_local(
                    vector_db_path,
                    kb_builder.embedding_model,
                    allow_dangerous_deserialization=True,
                )
                print(f"Database loaded in {time.time() - start_time:.2f} seconds.")
            else:
                print(f"No existing database found. Building a new one...")
                vector_database = kb_builder.build_vector_db(db_file_path)
                if vector_database:
                    print(f"Saving new vector database to '{vector_db_path}'...")
                    vector_database.save_local(vector_db_path)
                    print("Database saved successfully.")
            return vector_database
        vector_db = _build_vector_db()
        if not vector_db:
            raise ValueError("Vector database is not valid.")
        self.vector_db = vector_db
        self.llm_client = openai.Client(base_url=api_base, api_key="EMPTY")
        print("\nEnd-to-end RAG system is ready.")
        self.conversation_history=[]
        
    def classify_intent(self, user_input):
        """判断用户意图类型"""
        try:
            messages = [{'role': 'system', 'content': SYSTEM_PROMPT0}]
            messages.extend(self.conversation_history) # 注入历史记忆
            messages.append({'role': 'user', 'content': user_input})
            response = self.llm_client.chat.completions.create(
                model="default",
                messages = messages,
                # messages=[
                #     {"role": "system", "content": SYSTEM_PROMPT0},

                #     {"role": "user", "content": user_input},
                # ],
                temperature=0.8,
                max_tokens=1024,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            
            print(response.choices[0].message.content)
            intent = response.choices[0].message.content
            self._update_history(user_input,intent)
            if intent in ["A", "B", "C"]:
                return intent
            else:
                return "C"
        except Exception as e:
            print(f"❌ 意图分类错误: {str(e)}")
            return "C"
    def _update_history(self,user_input, ai_response):
        # 追加当前轮次
        self.conversation_history.append({'role': 'user', 'content': user_input})
        self.conversation_history.append({'role': 'assistant', 'content': ai_response})
        
        # 计算最大消息数 (3轮 * 2条/轮 = 6条)
        max_messages = MAX_HISTORY_ROUNDS * 2
        
        # 如果超出限制，切片保留最近的 N 条
        if len(self.conversation_history) > max_messages:
            self.conversation_history = self.conversation_history[-max_messages:]

    def chat(self, user_input,unvisited,current_landmark, top_k=20):
        start = time.time()
        unvisited_landmarks = json.dumps(
                    unvisited, ensure_ascii=False
                )
        user_input2 = user_input + f"\n 还没有去过的展区： {unvisited_landmarks};\n 现在所在的展区：{current_landmark}"
        intent = self.classify_intent(user_input2)
        print(f"input:{user_input}   ,识别意图: {intent}")
        # import pdb
        # pdb.set_trace()
        # A: 指令
        if "请立刻带我去" in user_input:
            intent = "A"
        if intent == "A":
            system_prompt = SYSTEM_PROMPT1
            try:
                messages = [{'role': 'system', 'content': SYSTEM_PROMPT1}]
                messages.extend(self.conversation_history) # 注入历史记忆
                messages.append({'role': 'user', 'content': user_input2})
                response = self.llm_client.chat.completions.create(
                    model="default",
                    messages=messages,
                    temperature=0.8,
                    max_tokens=1024,
                    extra_body={
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                ai_response = response.choices[0].message.content
                self._update_history(user_input,ai_response)
                if not is_valid_command(ai_response):
                    print("检测到非法指令，使用SYSTEM_PROMPT4重新生成..." + ai_response)
                    messages = [{'role': 'system', 'content': SYSTEM_PROMPT4}]
                    messages.extend(self.conversation_history) # 注入历史记忆
                    messages.append({'role': 'user', 'content': user_input2})
                    response = self.llm_client.chat.completions.create(
                        model="default",
                        messages=messages,
                        temperature=0.8,
                        max_tokens=1024,
                        extra_body={
                            "chat_template_kwargs": {"enable_thinking": False},
                        },
                    )
                    ai_response = response.choices[0].message.content
                    self._update_history(user_input2,ai_response)
                print(f"⏱️  响应时间: {time.time()-start:.2f}秒")
                return intent, ai_response

            except Exception as e:
                print(f"API调用错误: {str(e)}")
                return intent, f"抱歉，处理您的请求时出现了错误: {str(e)}"

        # B: 知识库问答
        elif intent == "B":
            print(f"\n========== New Query Received ==========")
            print(f"User question: \"{user_input}\"")
            print(f"Searching for top {top_k} relevant sentences...")
            results_with_scores = self.vector_db.similarity_search_with_score(user_input, k=top_k)
            if not results_with_scores:
                return intent, "抱歉，在知识库中没有找到与您问题相关的信息。"

            retrieved_sentences = [doc.page_content for doc, score in results_with_scores]
            unique_paragraphs_dict = OrderedDict()
            for doc, score in results_with_scores:
                unique_paragraphs_dict[doc.metadata.get("parent_paragraph", "")] = True
            unique_paragraphs = list(unique_paragraphs_dict.keys())

            print(
                f"Retrieval completed. Found {len(retrieved_sentences)} sentences and {len(unique_paragraphs)} unique paragraphs."
            )
            sentences_str = "\n".join(f"- {s}" for s in retrieved_sentences)
            paragraphs_str = "\n\n---\n\n".join(unique_paragraphs)
            final_user_prompt = USER_PROMPT_DATABASE.format(
                sentences=sentences_str,
                paragraphs=None,
                user_question=user_input,
            )
            # print("sentence_str:",sentences_str)
            print("Calling local LLM to generate the final answer...")
            start_time = time.time()
            try:
                messages = [{'role': 'system', 'content': SYSTEM_PROMPT_DATABASE}]
                messages.extend(self.conversation_history) # 注入历史记忆
                messages.append({'role': 'user', 'content': final_user_prompt})

                response = self.llm_client.chat.completions.create(
                    model="default",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=1024,
                    extra_body={
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                final_answer = response.choices[0].message.content
                self._update_history(user_input,final_answer)
            except Exception as e:
                print(f"Error calling LLM: {e}")
                return intent, "抱歉，调用语言模型时出错，请检查API服务是否正常。"
            print(f"LLM generation completed in {time.time() - start_time:.2f} seconds.")
            return intent, final_answer

        # C: 闲聊
        else:
            system_prompt = SYSTEM_PROMPT3
            messages = [{'role': 'system', 'content': system_prompt}]
            messages.extend(self.conversation_history) # 注入历史记忆
            messages.append({'role': 'user', 'content': user_input})
            response = self.llm_client.chat.completions.create(
                model="default",
                messages=messages,
                temperature=0.8,
                max_tokens=1024,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            ai_response = response.choices[0].message.content
            self._update_history(user_input,ai_response)
            return intent, ai_response
    def generate_unreachable_landmark(self,landmark_dict):
        lines = ["未参观点位列表："]
        for key, value in landmark_dict.items():
            lines.append(f"- {key}: {value}")
        user_content = "\n".join(lines)

        # 2) 调用本地 LLM 生成引导语
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_LANDMARK_NAV},
            {"role": "user", "content": user_content},
        ]

        t_llm0 = time.time()
        response = self.llm_client.chat.completions.create(
            model="default",
            messages=messages,
            temperature=0.7,
            max_tokens=256,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        t_llm1 = time.time()
        nav_text = response.choices[0].message.content.strip()
        print(f"[NAV] LLM nav text: {nav_text}")
        print(f"[NAV] LLM cost: {t_llm1 - t_llm0:.2f}s")
        return nav_text
        
def is_valid_command(response_text):
    """检查SYSTEM_PROMPT1的回复中指令是否合法"""
    lines = response_text.split("\n")
    if len(lines) >= 2 and lines[1].startswith("/"):
        command = lines[1].strip()
        valid_commands = [
            "manipulate",
            "/manipulate xitong",
            "/release xitong",
            "/move_to Landmark1",
            "/move_to Landmark2",
            "/move_to Landmark3",
            "/move_to Landmark4",
            "/move_to Landmark5",
            "/move_to Landmark6",
            "/move_to Landmark7",
            "/move_to Landmark8",
            "/start",
            "/resume",
            "/leave",
            "/NG"
        ]
        return command in valid_commands
    return True

def parse_command(item: str):
    item = item.lstrip("/")
    parts = item.split(maxsplit=1)
    if len(parts) == 1:
        return {"action": parts[0], "param": {"marker_id": ""}}
    else:
        command, param = parts
        return {"action": command, "param": {"marker_id": param}}
def parse_llm_result(intent: str, ai_response: str):
    if intent == "A":
        lines = ai_response.split("\n")
        ai_response = lines[0]
        if len(lines) > 1 :
            command = parse_command(lines[1])
        else :
            command = {"action": "talk", "param": ""}
    elif intent == "D":
        lines = ai_response.split("\n")
        ai_response = lines[0]
        if len(lines) > 1 :
            command = parse_command(lines[1])
        else :
            command = {"action": "talk", "param": ""}
    elif intent == "B":
        command = {"action": "talk_database", "param": ""}
    elif intent == "C":
        command = {"action": "talk", "param": ""}
    elif intent == "D":
        command = {"action": "stop", "param": ""}
    return command, ai_response