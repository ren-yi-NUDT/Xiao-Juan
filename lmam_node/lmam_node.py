#!/home/igraperobot3/anaconda3/envs/audio/bin/python3
# -*- coding: utf-8 -*-

import os, sys, glob
from ament_index_python.packages import get_package_share_directory, get_package_prefix

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..')
agent_pkg = get_package_share_directory('agent')
lmam_pkg = get_package_share_directory('lmam')
prefix = get_package_prefix('lmam')

# 尝试把安装到安装前缀里的 python 路径拉进来
candidate_py_paths = [
    os.path.join(prefix, 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages'),
    os.path.join(prefix, 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'dist-packages'),
    os.path.join(prefix, 'local', 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages'),
    os.path.join(prefix, 'local', 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'dist-packages'),
]
candidate_py_paths.extend(glob.glob(os.path.join(prefix, 'lib', 'python*', 'site-packages')))
candidate_py_paths.extend(glob.glob(os.path.join(prefix, 'lib', 'python*', 'dist-packages')))
candidate_py_paths.extend(glob.glob(os.path.join(prefix, 'local', 'lib', 'python*', 'site-packages')))
candidate_py_paths.extend(glob.glob(os.path.join(prefix, 'local', 'lib', 'python*', 'dist-packages')))
for p in candidate_py_paths:
    if p and os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

sys.path.insert(0, project_root)
sys.path.insert(0, agent_pkg)
sys.path.insert(0, lmam_pkg)

import numpy as np
import time
import json
import asyncio
import threading
import websockets
import select

import rclpy
from rclpy.action import CancelResponse

from components.base import Base
from std_msgs.msg import Bool, String
from agent.msg import StateMsg
from agent.action import Command
from lmam.action import AudioControl

from local_listener import VoiceListener
from llm import LLM_ASSISTENT, parse_llm_result
from tts_ws_streamer import TTSWsStreamer

from wakeup import XiaoYunKWS, SharedState, ClientControlState

from matcher import ExhibitIntentMatcher
from NG_config import NG_LANDMARK_CONFIG, NG_TTS_CONFIG, NG_TTS_TXT, QILIN_TTS_CONFIG

# =========================
# 你可调的参数
# =========================
KWS_KEYWORD = "小云小云"
KWS_RMS_GATE = 0.01

SESSION_HOLD_SEC = 15.0         # ✅ 唤醒一次后，会话保持窗口
AUTO_RESUME_SILENCE_SEC = 0.5    # ✅ 连续静默多久自动恢复讲解
RESUME_CHECK_PERIOD = 0.2        # ✅ 0.2s 检查一次（5Hz）

# ✅ 自动恢复讲解只在 IDLE 执行（推荐）
ONLY_RESUME_WHEN_IDLE = True
landmark_to_name = {
    'Landmark1': 'xxxx',
    'Landmark2': 'xxxx',
    'Landmark3': 'xxxx',
    'Landmark4': 'xxxx',
    'Landmark5': 'xxxx',
    'Landmark6': 'xxxx',
    'Landmark7': 'xxxx',
    'Landmark8': 'xxxx',
}

class LMAM(Base):
    def __init__(self):
        super().__init__('lmam')

        # ====== ROS pubs/subs ======
        self.state_topic = f'state_interface/{self.name}'
        self.state_publisher = self.create_publisher(StateMsg, self.state_topic, 10)
        self.state_timer = self.create_timer(1.0 / 30, self.state_pub)
        
        self.create_subscription(String, "/audio_done", self._audio_done_cb, 10)
        self.create_subscription(Bool, "/tts_playing", self._tts_playing_cb, 20)
        self.create_subscription(StateMsg, '/agent_info', self.update_agent_info, 10)
        
        # ====== 状态机 ======
        self.shared_state = SharedState()  # mode: IDLE/ACTIVE
        self.ctrl = ClientControlState()

        # 会话窗口（唤醒一次后 N 秒内不需要重复唤醒）
        self.session_hold_sec = float(SESSION_HOLD_SEC)
        self.awake_until_ts = 0.0

        # 静默计时（用于 8s 自动 resume）
        self.last_activity_ts = time.time()

        # 讲解是否处于“断点待续播”
        self.guide_paused = False

        # 自动 resume 控制
        self.resume_inflight = False
        self.pause_deadline_sec = float(AUTO_RESUME_SILENCE_SEC)
        self.resume_timer = self.create_timer(float(RESUME_CHECK_PERIOD), self._resume_check_cb)

        # ====== KWS ======
        self.kws = XiaoYunKWS(sample_rate=16000, keyword=KWS_KEYWORD)
        self.kws_rms_gate = float(KWS_RMS_GATE)

        # ====== Orin 音频控制 ActionClient ======
        self.start_audio_client = rclpy.action.ActionClient(self, AudioControl, 'audio_control')


        # ====== ASR ======
        self.local_listener = VoiceListener(
            model_path_or_size="/home/igraperobot3/Model/faster-whisper-large-v3",
            device="cuda"
        )

        # ====== LLM ======
        self.assistant = LLM_ASSISTENT()
        self.unvisited_landmarks = None
        # ====== TTS streamer (x86 -> Orin by WS) ======
        self.tts_streamer = TTSWsStreamer(
            config_path="/home/igraperobot3/Model/melo/ZH/config.json",
            ckpt_path="/home/igraperobot3/Model/melo/ZH/checkpoint.pth",
            device="cuda",
            speed=1.0,
            chunk_size=64 * 1024,
            sample_rate=22050,
        )

        # ====== WS server thread ======
        self.ws_loop = asyncio.new_event_loop()
        self.ws_thread = threading.Thread(target=self._start_ws_server, daemon=True)
        self.ws_send_lock = None
        self.current_ws = None
        self.ws_thread.start()
        self.leave_send = False

        # ====== ASR->LLM->TTS queue/consumer ======
        self.asr_text_queue: asyncio.Queue = asyncio.Queue()

        def _start_consumers():
            asyncio.set_event_loop(self.ws_loop)
            self.ws_send_lock = asyncio.Lock()
            self.ws_loop.create_task(self._asr_text_consumer())

        self.ws_loop.call_soon_threadsafe(_start_consumers)

        # ====== mic thread ======
        self._enter_idle("boot")
        self.mic_stop = threading.Event()
        self.mic_thread = threading.Thread(target=self._mic_worker, daemon=True)
        self.mic_thread.start()

        # 讲解结束后是否播提示语（保留你的字段）
        self.audio_done_path = ""
        self.txt_command = ""
        self.idle_timeout = None
        self.get_logger().info("[LMAM] started. ws thread + mic thread ready.")

        self.last_command = None
        self.last_replytxt = None
        self.idle_txt = None

        self.visited_landmarks = [] # 参观过的展区

        self.current_landmark = 'Landmark0' # 当前正在参观的展区
    
    
    def update_agent_info(self, msg):
        data = json.loads(msg.data)
        recieve_landmark = data['current_landmark']
        self.current_landmark = recieve_landmark
        

    # =========================
    # mic worker
    # =========================
    def _mic_worker(self):
        while not self.mic_stop.is_set():
            # print(self.shared_state.mode,len(self.unvisited_landmarks) if self.unvisited_landmarks is not None else None,(time.time() - self.idle_timeout) if self.idle_timeout is not None else "no timeout",self.leave_send)
            if self.shared_state.mode == "IDLE" and self.unvisited_landmarks is not None and len(self.unvisited_landmarks) == 0:
                # import pdb
                # pdb.set_trace()
                if self.idle_timeout is not None and time.time() - self.idle_timeout > 3 and self.leave_send == False :
                    msg = StateMsg()
                    msg.name = "lmam"
                    msg.data = json.dumps({"action":"leave","param": {}}, ensure_ascii=False)
                    self.state_publisher.publish(msg)
                    self.leave_send = True
                    # print("have send leave to agent")
            try:
                mode = self.shared_state.mode
            except Exception:
                mode = "IDLE"

            # ========== IDLE：只做 KWS ==========
            if mode == "IDLE":
                try:
                    pcm = self.local_listener.read_kws_pcm_16k(duration_sec=0.2)
                except Exception as e:
                    self.get_logger().warn(f"[KWS] read_kws_pcm_16k failed: {e}")
                    time.sleep(0.05)
                    continue

                if self.kws.feed(pcm):
                    if self.ctrl.can_send("WAKE", min_interval=2.0):
                        # 1) 打断 Orin：mp3->checkpoint pause / stream->stop
                        self.get_logger().info("[LMAM] wake word detected -> interrupt orin")
                        self.send_interrupt_to_orin()

                        # 2) 标记：讲解断点待续播（后续静默 8s 自动 resume）
                        
                        if self.shared_state.audio_playing:
                            self.guide_paused = True
                            self.shared_state.set_audio_playing(False, None)

                        # 4) 播唤醒提示语
                        asyncio.run_coroutine_threadsafe(
                            self._play_wakeup_prompt("您好，我在。"),
                            self.ws_loop
                        )
                        # 5) 进入 ACTIVE
                        self._enter_active("wakeup")
                        self.idle_timeout = None
                        self.last_activity_ts = time.time()
                continue

            # ========== ACTIVE：ASR ==========
            try:
                try:
                    self.local_listener.close_kws_stream()
                except Exception:
                    pass

                result_text = self.local_listener.listen_and_transcribe()
                if result_text and result_text.strip():
                    text = result_text.strip()

                    # 投递到 ws_loop 的 queue
                    self.ws_loop.call_soon_threadsafe(
                        self.asr_text_queue.put_nowait,
                        text
                    )

                # 超时回到 IDLE（你定义 IDLE_TIMEOUT）
                if not self.shared_state.tts_playing:
                    self.idle_timeout = self.shared_state.maybe_back_to_idle()
                if self.idle_timeout is not None and not self.guide_paused and not self.shared_state.audio_playing and not self.shared_state.tts_playing:
                    # print("如果您有任何问题请呼唤两声小云唤醒我哦。")
                    asyncio.run_coroutine_threadsafe(
                            self._play_backtoIDLE_prompt("如果您有任何问题请呼唤两声小云唤醒我哦。"),
                            self.ws_loop
                        )
                if self.shared_state.mode == "IDLE":
                    self.get_logger().info("[LMAM] Back to IDLE")
                
            except Exception as e:
                self.get_logger().error(f"[mic] error: {e}")
                time.sleep(0.05)
            
    # =========================
    # 自动续播：循环检测静默 >= 8s -> resume mp3
    # =========================
    def _resume_check_cb(self):
        # import pdb
        # pdb.set_trace()
        # print("audio_playing",self.shared_state.audio_playing,"resume_flag:",self.resume_inflight,"guided_paused:",self.guide_paused,"shared_state.tts_playing",self.shared_state.tts_playing)
        if self.resume_inflight:
            return
        if not self.guide_paused:
            return
        if self.shared_state.tts_playing:
            return
        if ONLY_RESUME_WHEN_IDLE and self.shared_state.mode != "IDLE":
            return
        print("start to resume time")
        elapsed = time.time() - float(self.last_activity_ts)
        # print("elapsed", elapsed)
        if elapsed >= self.pause_deadline_sec:
            self.resume_inflight = True
            print("resume to here")
            asyncio.run_coroutine_threadsafe(self._auto_resume_mp3_once(), self.ws_loop)

    async def _auto_resume_mp3_once(self):
        if self.ws_send_lock is None:
            self.ws_send_lock = asyncio.Lock()
        self.shared_state.set_tts_playing(True, None)
        self._enter_idle("orin playing")
        await self.tts_streamer.speak("我继续为您讲解", self.current_ws, self.ws_send_lock)
        self.shared_state.set_audio_playing(True, None)
        # import pdb
        # pdb.set_trace()
        try:
            print("to this")
            ok = await asyncio.to_thread(self._send_audio_resume_to_orin)
            if ok:
                self.guide_paused = False
                self.get_logger().info("[LMAM] auto-resume mp3 success -> guide_paused=False")
            else:
                self.get_logger().warn("[LMAM] auto-resume mp3 failed -> will retry in next silence window")
        except Exception as e:
            self.get_logger().warn(f"[auto_resume] exception: {e}")
        finally:
            self.resume_inflight = False

    def _send_audio_resume_to_orin(self) -> bool:
        if not self.start_audio_client.wait_for_server(timeout_sec=0.5):
            self.get_logger().warn("[LMAM] audio_control not available for audio_resume")
            return False
        ok, msg = self.call_audio_control("audio_resume", "", goal_handle=None)
        self.get_logger().info(f"[LMAM] audio_resume -> success={ok}, message={msg}")
        return bool(ok)

    # =========================
    # 播放唤醒提示语
    # =========================
    async def _play_wakeup_prompt(self, text: str = "您好，我在。"):
        if self.current_ws is None:
            return
        if self.ws_send_lock is None:
            self.ws_send_lock = asyncio.Lock()
        try:
            self._enter_idle("wakeup prompt tts")
            await self.tts_streamer.speak(text, self.current_ws, self.ws_send_lock)
            self.idle_txt = None
        except Exception as e:
            self.get_logger().warn(f"[wakeup_prompt] failed: {e}")
    async def _play_backtoIDLE_prompt(self, text: str = "如果您有任何问题请呼唤两声小云唤醒我哦。"):
        if self.current_ws is None:
            return
        if self.ws_send_lock is None:
            self.ws_send_lock = asyncio.Lock()
        try:
            self.idle_txt = "如果您有任何问题请呼唤两声小云唤醒我哦。"
            self._enter_idle("wakeup prompt tts")
            await self.tts_streamer.speak(text, self.current_ws, self.ws_send_lock)
        except Exception as e:
            self.get_logger().warn(f"[wakeup_prompt] failed: {e}")
    # =========================
    # LLM + consumer
    # =========================
    async def run_llm(self, text: str):
        def _call():
            intent, ai_response = self.assistant.chat(text,self.unvisited_landmarks,self.current_landmark)
            return parse_llm_result(intent, ai_response)
        return await asyncio.to_thread(_call)

    async def _asr_text_consumer(self):
        while True:
            text = (await self.asr_text_queue.get()).strip()
            if not text:
                continue
            if "志愿者" in text or "杨茜茜" in text or "字幕" in text or "转发" in text or "明镜" in text or "转发" in text or "观看" in text or "感谢观看" in text or "谢谢" in text or "搅拌" in text:
                continue

            # 只在 ACTIVE 才处理
            if self.shared_state.mode != "ACTIVE":
                continue
            ### how to start
            start_flag = 0
            # confirm_flag = 0
            # content_start = ''

            for start_instant in reversed(list(self.assistant.conversation_history)):
                content_start = start_instant['content']    

                # print('[debug_start1]',start_flag)
                if "是否可以开始今天的展览" in content_start:
                    start_flag = 1
                    ## 从list(self.assistant.conversation_history)中将“"是否可以开始今天的展览"”删除、
                    self.assistant.conversation_history = [item for item in self.assistant.conversation_history if "是否可以开始今天的展览" not in item['content']]
                    break
                # if self.last_command is not None :
                #     if "请问我们要直接前往{}展区吗".format(landmark_to_name[self.last_command['param']['marker_id']]) in content_start:
                #         confirm_flag = 1
                #         # self.last_command = None
                #         # self.last_replytxt = None
                #         break
                # ## 参观重复展区
                #     if "我们已经参观过{}展区了,您有什么问题可以直接问我哦".format(landmark_to_name[self.last_command['param']['marker_id']]) in content_start:
                #         confirm_flag = 1
                #         break
                        # self.last_command = None
                        # self.last_replytxt = None
                      
            # print('[debug_start2]',start_flag)
            if start_flag == 1 :
                if "可以" in text or "好" in text or "是" in text or "始" in text or "嗯" in text or "没问题" in text or "行" in text or "OK" in text or "就绪" in text or "来吧" in text or "走着" in text or "出发" in text:
                    command, reply_text = {"action": "start", "param": {}}, ''
                    # publish state
                    try:
                        msg = StateMsg()
                        msg.name = "lmam"
                        msg.data = json.dumps(command, ensure_ascii=False)
                        self.state_publisher.publish(msg)
                        self.last_command = None
                        self.last_replytxt = None
                        self.visited_landmarks.append(landmark_to_name['Landmark1'])
                        # print("[debug_confirm] visited_landmarks",self.visited_landmarks)
                        continue
                    except Exception as e:
                        self.get_logger().warn(f"[ROS] publish LLM reply failed: {e}")

                    if self.current_ws is None:
                        self.get_logger().warn("[WS] no orin connected, drop tts.")
                        self._enter_idle("no ws")
                        continue
            #####
            # if confirm_flag == 1 :
            #     if "可以" in text or "好" in text or "是" in text or "开始" in text or "嗯" in text or "没问题" in text or "行" in text or "OK" in text or "就绪" in text or "来吧" in text or "走着" in text or "出发" in text or "去" in text:
            #         command,reply_text = self.last_command,self.last_replytxt
            #         self.visited_landmarks.append(landmark_to_name[self.last_command['param']['marker_id']])
            #         self.current_landmark = landmark_to_name[self.last_command['param']['marker_id']]
            #         # print("[debug_confirm] visited_landmarks",self.visited_landmarks)
            #         try:
            #             msg = StateMsg()
            #             msg.name = "lmam"
            #             msg.data = json.dumps(command, ensure_ascii=False)
            #             self.state_publisher.publish(msg)
            #             self.last_command = None
            #             self.last_replytxt = None
            #             continue
            #         except Exception as e:
            #             self.get_logger().warn(f"[ROS] publish LLM reply failed: {e}")

            #         if self.current_ws is None:
            #             self.get_logger().warn("[WS] no orin connected, drop tts.")
            #             self._enter_idle("no ws")
            #             continue

            #         # 播放期间不听
            #         self._enter_idle("tts outgoing")
            #         self.shared_state.set_tts_playing(True, None)
            #         if self.ws_send_lock is None:
            #             self.ws_send_lock = asyncio.Lock()
            #         self.shared_state.set_tts_playing(True, None)
            #         self._enter_idle("tts playing")
            #         await self.tts_streamer.speak(reply_text, self.current_ws, self.ws_send_lock)
            #         continue

            self.last_activity_ts = time.time()
            # import pdb
            # pdb.set_trace()
            #### 2025/12/31  NG 展区识别各个展品 >>>>>>>>>>>>>>>
            if self.current_landmark == 'Landmark2':
                NG_landmark = ExhibitIntentMatcher(NG_LANDMARK_CONFIG)
                NG_tts = ExhibitIntentMatcher(NG_TTS_CONFIG)
                NG_landmark_id = NG_landmark.predict(text)
                NG_TTS_id = NG_tts.predict(text)
                if NG_landmark_id['success'] :
                    command, reply_text = {"action": "NG", "param": {'id': NG_landmark_id['product_id']}}, ''
                    self.last_command = command
                    try:
                        msg = StateMsg()
                        msg.name = "lmam"
                        msg.data = json.dumps(command, ensure_ascii=False)
                        self.state_publisher.publish(msg)
                        # self.last_command = None
                        # self.last_replytxt = None
                    # continue
                    except Exception as e:
                        self.get_logger().warn(f"[ROS] publish LLM reply failed: {e}")

                    if self.current_ws is None:
                        self.get_logger().warn("[WS] no orin connected, drop tts.")
                        self._enter_idle("no ws")
                        continue
                else :
                    self.last_command = None


                if NG_TTS_id['success'] :
                    reply_text = NG_TTS_TXT[NG_TTS_id['product_id']]
                    try:
                        if self.ws_send_lock is None:
                            self.ws_send_lock = asyncio.Lock()
                        # print(f"[reply]  {reply_text}")
                        await self.tts_streamer.speak(reply_text, self.current_ws, self.ws_send_lock)
                        # time.sleep(1)
                        continue
                        # self.last_command = None
                        # self.last_replytxt = None
                    # continue
                    except Exception as e:
                        self.get_logger().warn(f"[ROS] publish LLM reply failed: {e}")

                    if self.current_ws is None:
                        self.get_logger().warn("[WS] no orin connected, drop tts.")
                        self._enter_idle("no ws")
                        continue
            
            if self.current_landmark == 'Landmark4' or self.current_landmark == 'Grasp1' or self.current_landmark == 'Return1':
                QL_TTS_grasp = ExhibitIntentMatcher(QILIN_TTS_CONFIG)
                QL_TTS_grasp_id = QL_TTS_grasp.predict(text)
                if QL_TTS_grasp_id['success'] :
                    command, reply_text = {"action": "manipulate", "param": {}}, ''
                    self.last_command = command
                    if self.ws_send_lock is None:
                        self.ws_send_lock = asyncio.Lock()
                    await self.tts_streamer.speak("没问题，这就拿给您看一看", self.current_ws, self.ws_send_lock)
                    try:
                        msg = StateMsg()
                        msg.name = "lmam"
                        msg.data = json.dumps(command, ensure_ascii=False)
                        self.state_publisher.publish(msg)
                        # self.last_command = None
                        # self.last_replytxt = None
                        continue
                    except Exception as e:
                        self.get_logger().warn(f"[ROS] publish LLM reply failed: {e}")

                    if self.current_ws is None:
                        self.get_logger().warn("[WS] no orin connected, drop tts.")
                        self._enter_idle("no ws")
                        continue
                else :
                    self.last_command = None
            #### <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

            try:
                command, reply_text = await self.run_llm(text)
                # print(command)
                # 执行 move_to 前加 确认词
                # print("[DeBUG] landmark_to_name", landmark_to_name[command['param']['marker_id']])
                # if command['action'] == 'move_to' and landmark_to_name[command['param']['marker_id']] in self.unvisited_landmarks['landmarks'].values():
                # print("[debug_ifout] visited_landmarks",self.visited_landmarks)
                # import pdb
                # pdb.set_trace()
                if command['action'] == 'move_to':
                    # print(f"whether landmark in visited_landmarks:{command['param']['marker_id']},{self.visited_landmarks},{command['param']['marker_id'] not in self.visited_landmarks}")
                    # if landmark_to_name[command['param']['marker_id']] not in self.visited_landmarks:
                    if command['param']['marker_id'] in self.unvisited_landmarks:
                        try:
                            if self.last_command is None or (self.last_command is not None and self.last_command['action'] != "NG"):
                                msg = StateMsg()
                                msg.name = "lmam"
                                msg.data = json.dumps(command, ensure_ascii=False)
                                self.state_publisher.publish(msg)
                                self._enter_idle("tts outgoing")
                                self.shared_state.set_tts_playing(True, None)
                                # self.visited_landmarks.append(landmark_to_name[command['param']['marker_id']])
                                self.last_command = None
                            if self.ws_send_lock is None:
                                self.ws_send_lock = asyncio.Lock()
                            await self.tts_streamer.speak(reply_text, self.current_ws, self.ws_send_lock)
                            continue
                        except Exception as e:
                            self.get_logger().warn(f"[ROS] publish LLM reply failed: {e}")

                        if self.current_ws is None:
                            self.get_logger().warn("[WS] no orin connected, drop tts.")
                            self._enter_idle("no ws")
                            continue

                    else:
                        self.assistant.conversation_history.append({'role': 'assistant', 'content': "我们已经参观过{}展区了,您有什么问题可以直接问我哦".format(landmark_to_name[command['param']['marker_id']])})
                        self.shared_state.set_tts_playing(True, None)
                        self._enter_idle("tts playing")
                        await self.tts_streamer.speak("我们已经参观过{}展区了,您有什么问题可以直接问我哦".format(landmark_to_name[command['param']['marker_id']]), self.current_ws, self.ws_send_lock)
                        continue
                elif  command['action'] == 'resume':
                    asyncio.run_coroutine_threadsafe(self._auto_resume_mp3_once(), self.ws_loop)
                # publish state
                elif command['action'] == 'leave':
                    msg = StateMsg()
                    msg.name = "lmam"
                    msg.data = json.dumps({"action":"leave","param": {}}, ensure_ascii=False)
                    self.state_publisher.publish(msg)
                    self.leave_send = True
                else:
                    try:
                        msg = StateMsg()
                        msg.name = "lmam"
                        msg.data = json.dumps(command, ensure_ascii=False)
                        self.state_publisher.publish(msg)
                    except Exception as e:
                        self.get_logger().warn(f"[ROS] publish LLM reply failed: {e}")

                    if self.current_ws is None:
                        self.get_logger().warn("[WS] no orin connected, drop tts.")
                        self._enter_idle("no ws")
                        continue

                    # 播放期间不听
                    self._enter_idle("tts outgoing")
                    self.shared_state.set_tts_playing(True, None)
                    if self.ws_send_lock is None:
                        self.ws_send_lock = asyncio.Lock()
                    self.shared_state.set_tts_playing(True, None)
                    self._enter_idle("tts playing")
                    await self.tts_streamer.speak(reply_text, self.current_ws, self.ws_send_lock)
            except Exception as e:
                self.get_logger().error(f"[ASR->LLM->TTS] error: {e}")

    # =========================
    # Orin 播放状态回调：关键修复点
    # =========================
    def _tts_playing_cb(self, msg: Bool):
        if msg.data:
            self.shared_state.set_tts_playing(True, None)
            self._enter_idle("orin playing")
            return
        else:
            # 播放停止/暂停：不要无脑 ACTIVE！
            # print("tts done")
            self.shared_state.set_tts_playing(False, None)
            # print(f"if audio playing:{self.shared_state.audio_playing}")
            if self.shared_state.audio_playing:
                # Orin 还在播音频，不处理
                self._enter_idle("orin audio playing")
                return
            else :
                # time.sleep(1)
                # print(f"no audio playing, idle_txt: {self.idle_txt} ")
                if self.idle_txt is None or "如果您有任何问题请呼唤两声小云唤醒我" not in self.idle_txt :
                    self._enter_active("no audio playing")
                self.kws.last_user_activity = time.time()
                return
        

    def _audio_done_cb(self, msg: String):
        try:
            message = json.loads(msg.data)
        except Exception:
            self.get_logger().warn(f"[LMAM] /audio_done invalid json: {msg.data}")
            return

        status = message.get('status', '')
        path = message.get('path', '')
        if status == 'finished' or status =='interrupt':
            print("status == finished, set audio_playing False")
            self.shared_state.set_audio_playing(False, None)
        # 只处理 finished
        if status != "finished":
            self.get_logger().info(f"[LMAM] /audio_done: status={status}, path={path} (ignored)")
            return

        self.get_logger().info(f"[LMAM] Received audio_done 'finished' for path={path}")

        # 讲解自然结束：不再待续播
        self.guide_paused = False
        self.audio_done_path = path

    # =========================
    # 给 Orin 发 interrupt：mp3 checkpoint pause / stream stop
    # =========================
    def send_interrupt_to_orin(self):
        if not self.start_audio_client.wait_for_server(timeout_sec=0.5):
            self.get_logger().warn("[LMAM] audio_control not available for interrupt")
            return
        goal = AudioControl.Goal()
        goal.command = "interrupt"
        goal.path = ""
        self.start_audio_client.send_goal_async(goal)

    # =========================
    # Command 接口（保留你的原逻辑）
    # =========================
    def cmd_recieve_and_execute(self, goal_handle):
        goal = goal_handle.request
        cmd_name = goal.cmd_name
        params = json.loads(goal.params_json) if goal.params_json else {}
        self.get_logger().info(f"[{self.name}] Received command: {cmd_name}, params: {params}")
        if cmd_name == "unvisited_landmarks":
            self.unvisited_landmarks = params.get("landmarks", {})
            # self._enter_active("interact")
            goal_handle.succeed()
            return Command.Result(success=True, message="[LMAM] unvisited_landmarks updated.")
        if cmd_name == "interact_start":
            self._enter_active("interact_start by agent")
            goal_handle.succeed()
            return Command.Result(success=True, message="[LMAM] interact_start handled.")
        if cmd_name == "interact_stop": 
            self._enter_idle("interact_stop by agent")
            goal_handle.succeed()
            return Command.Result(success=True, message="[LMAM] interact_stop handled.")
        if cmd_name == "audio_start":
            self._enter_idle("audio_start")
            path = params.get("path", "")
            txt  = params.get("txt", "")
            # self.shared_state.set_audio_playing(True, None)
            if path:
                # 开始讲解：不处于待续播
                self.guide_paused = False
                ok, msg = self.call_audio_control("audio_start", path, goal_handle)
                if ok:
                    goal_handle.succeed()
                else:
                    goal_handle.abort()
                return Command.Result(success=ok, message=msg)

            if txt:
                if self.current_ws is None:
                    self.get_logger().warn("[LMAM] audio_start txt but no WebSocket.")
                else:
                    async def _tts_task_for_txt():
                        try:
                            self.assistant.conversation_history.append({'role': 'assistant', 'content': txt})
                            if self.ws_send_lock is None:
                                self.ws_send_lock = asyncio.Lock()
                                self.shared_state.set_tts_playing(True, None)
                            await self.tts_streamer.speak(txt, self.current_ws, self.ws_send_lock)
                        except Exception as e:
                            self.get_logger().warn(f"[audio_start txt] failed: {e}")
                    asyncio.run_coroutine_threadsafe(_tts_task_for_txt(), self.ws_loop)

                goal_handle.succeed()
                return Command.Result(success=True, message="[LMAM] audio_start with txt handled.")

            msg = "[LMAM] audio_start needs 'path' or 'txt'."
            self.get_logger().warn(msg)
            goal_handle.abort()
            return Command.Result(success=False, message=msg)
        if cmd_name == "audio_pause":
            # 外部 pause：认为讲解待续播
            self.guide_paused = True
            ok, msg = self.call_audio_control("audio_pause", "", goal_handle)
            if ok:
                goal_handle.succeed()
            else:
                goal_handle.abort()
            return Command.Result(success=ok, message=msg)

        if cmd_name == "audio_resume":
            ok, msg = self.call_audio_control("audio_resume", "", goal_handle)
            if ok:
                self.guide_paused = False
                goal_handle.succeed()
            else:
                goal_handle.abort()
            return Command.Result(success=ok, message=msg)
            # asyncio.run_coroutine_threadsafe(self._auto_resume_mp3_once(), self.ws_loop)
        if cmd_name == "audio_stop":
            self.guide_paused = False
            ok, msg = self.call_audio_control("audio_stop", "", goal_handle)
            if ok:
                goal_handle.succeed()
            else:
                goal_handle.abort()
            return Command.Result(success=ok, message=msg)

        if cmd_name == "stop":
            self.mic_stop.set()
            self.send_interrupt_to_orin()
        goal_handle.succeed()
        return Command.Result(success=True, message="Executed")

    def call_audio_control(self, command: str, path: str, goal_handle):
        if not self.start_audio_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("[LMAM] /audio_control action server not available.")
            return False, "audio_control not available"
        self._enter_idle("start_audio")
        goal_msg = AudioControl.Goal()
        goal_msg.command = command
        goal_msg.path = path or ""
        if command == "audio_start" or command == "audio_resume":
            self.shared_state.set_audio_playing(True, None)
            self.idle_txt = None
        send_future = self.start_audio_client.send_goal_async(goal_msg)

        while not send_future.done():
            if goal_handle is not None and goal_handle.is_cancel_requested:
                return False, "canceled before accept"
            time.sleep(0.01)

        goal_handle_ros = send_future.result()
        if not goal_handle_ros.accepted:
            return False, "rejected"

        result_future = goal_handle_ros.get_result_async()
        while not result_future.done():
            if goal_handle is not None and goal_handle.is_cancel_requested:
                return False, "canceled while waiting result"
            time.sleep(0.02)

        result_wrapper = result_future.result()
        result = result_wrapper.result
        return bool(result.success), result.message

    # =========================
    # Base 抽象接口
    # =========================
    def cancel_callback(self, goal_handle):
        self.get_logger().info('Cancel request received!')
        return CancelResponse.ACCEPT

    def _enter_idle(self, reason: str = ""):
        self.shared_state.set_mode("IDLE")
        self.idle_timeout = time.time()
        self.get_logger().info(f"[LMAM] -> IDLE ({reason})")

    def _enter_active(self, reason: str = ""):
        self.shared_state.wake()
        self.get_logger().info(f"[LMAM] -> ACTIVE ({reason})")

    def state_pub(self):
        pass

    def key_pressed(self):
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        return dr != []

    def get_current_state(self):
        return self.state

    def stop(self):
        pass

    # =========================
    # WebSocket server (x86)
    # =========================
    def _start_ws_server(self):
        asyncio.set_event_loop(self.ws_loop)
        self.ws_loop.run_until_complete(self._async_ws_main())

    async def _async_ws_main(self):
        async def ws_handler(websocket):
            self.get_logger().info("[LMAM] WebSocket connected.")
            self.current_ws = websocket
            try:
                await asyncio.Future()
            except websockets.ConnectionClosed:
                pass
            finally:
                self.get_logger().info("[LMAM] WebSocket disconnected.")
                self.current_ws = None

        async with websockets.serve(
            ws_handler,
            "0.0.0.0",
            9009,
            ping_interval=360,
            ping_timeout=360,
            close_timeout=360,
            max_size=100 * 1024 * 1024
        ):
            self.get_logger().info("[LMAM] WS server at ws://0.0.0.0:9009")
            await asyncio.Future()


def main(args=None):
    rclpy.init(args=args)
    lmam_node = LMAM()

    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(lmam_node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        lmam_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
