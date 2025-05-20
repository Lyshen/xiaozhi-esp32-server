#!/bin/bash

# 小智ESP32服务器Docker容器重启脚本
# 作用：停止现有容器，确保本地代码挂载，并重启服务

# 输出彩色文本
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}开始重启小智ESP32服务器容器...${NC}"

# 1. 确保docker-compose.override.yml文件存在（用于挂载本地代码）
if [ ! -f docker-compose.override.yml ]; then
    echo -e "${YELLOW}创建docker-compose.override.yml文件用于挂载本地代码...${NC}"
    cat > docker-compose.override.yml << 'EOF'
version: '3'
services:
  xiaozhi-esp32-server:
    volumes:
      # 本地代码目录挂载，确保修改的doubao.py和其他文件生效
      - ./main/xiaozhi-server:/opt/xiaozhi-esp32-server
      # 保留原有的挂载
      - ./data:/opt/xiaozhi-esp32-server/data
      - ./models/SenseVoiceSmall/model.pt:/opt/xiaozhi-esp32-server/models/SenseVoiceSmall/model.pt
EOF
    echo -e "${GREEN}docker-compose.override.yml创建成功${NC}"
fi

# 2. 停止当前运行的容器
echo -e "${YELLOW}停止当前运行的容器...${NC}"
docker stop xiaozhi-esp32-server || true

# 3. 使用docker-compose启动容器（会自动应用override文件）
echo -e "${YELLOW}使用docker-compose启动服务...${NC}"
docker-compose up -d

# 4. 检查容器是否正常启动
echo -e "${YELLOW}检查容器状态...${NC}"
if docker ps | grep -q xiaozhi-esp32-server; then
    echo -e "${GREEN}容器启动成功！${NC}"
    echo -e "${YELLOW}查看最新日志...${NC}"
    docker logs --tail 10 xiaozhi-esp32-server
else
    echo -e "${YELLOW}容器启动失败，请检查错误信息：${NC}"
    docker-compose logs xiaozhi-esp32-server
fi

echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}重启操作完成${NC}"
echo -e "${GREEN}WebSocket服务器运行在: http://localhost:8000${NC}"
echo -e "${GREEN}==========================================${NC}"
