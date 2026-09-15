cmake_minimum_required(VERSION 3.8)
project(lmam)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# 基本依赖
find_package(ament_cmake REQUIRED)
find_package(rclpy REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# 生成 action 接口
rosidl_generate_interfaces(${PROJECT_NAME}
  "action/StartClient.action"
  "action/AudioControl.action"
  DEPENDENCIES builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)

# 安装 Python 节点脚本（给 ros2 run 用）
install(
  PROGRAMS
    scripts/llm.py
    scripts/local_listener.py
    scripts/tts_ws_streamer.py
    lmam_node/lmam_node.py
    scripts/wakeup.py
    scripts/FT_config.py
    scripts/matcher.py
  DESTINATION lib/${PROJECT_NAME}
)

# 安装 prompts 目录（如果里边只是数据/脚本,保持也行）
install(
  DIRECTORY prompts
  DESTINATION lib/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE
)

ament_package()
