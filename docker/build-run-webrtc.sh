#!/bin/bash

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}==================================================${NC}"
echo -e "${BLUE}     构建并启动WebRTC测试版本      ${NC}"
echo -e "${BLUE}==================================================${NC}"

# 确保脚本从docker目录运行
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查是否有配置文件，如果没有则创建基本配置
if [ ! -f "../data/webrtc.config.yaml" ]; then
    echo -e "${YELLOW}未找到WebRTC配置文件，正在创建默认配置...${NC}"
    cp ../data/webrtc_config_sample.yaml ../data/webrtc.config.yaml
    echo -e "${GREEN}已创建默认配置文件: ../data/webrtc.config.yaml${NC}"
fi

# 停止并移除现有容器（如果存在）
echo -e "${BLUE}停止并移除现有WebRTC测试容器（如果存在）...${NC}"
docker-compose -f docker-compose-webrtc.yml down

# 构建镜像
echo -e "${BLUE}开始构建WebRTC测试镜像...${NC}"
docker-compose -f docker-compose-webrtc.yml build

# 如果构建成功，启动容器
if [ $? -eq 0 ]; then
    echo -e "${GREEN}镜像构建成功！正在启动WebRTC测试容器...${NC}"
    docker-compose -f docker-compose-webrtc.yml up -d
    
    # 检查容器是否成功启动
    sleep 3
    CONTAINER_STATE=$(docker inspect --format='{{.State.Running}}' xiaozhi-webrtc-test 2>/dev/null)
    
    if [ "$CONTAINER_STATE" = "true" ]; then
        echo -e "${GREEN}WebRTC测试容器已成功启动！${NC}"
        echo -e "${GREEN}WebSocket服务器地址: ws://$(hostname -I | awk '{print $1}'):8000${NC}"
        echo -e "${GREEN}WebRTC信令服务器地址: ws://$(hostname -I | awk '{print $1}'):8082/ws/signaling${NC}"
        echo -e "${YELLOW}查看容器日志: docker logs -f xiaozhi-webrtc-test${NC}"
    else
        echo -e "${RED}容器启动失败，请检查错误信息。${NC}"
        docker-compose -f docker-compose-webrtc.yml logs
    fi
else
    echo -e "${RED}镜像构建失败，请检查错误信息。${NC}"
fi

echo -e "${BLUE}==================================================${NC}"
