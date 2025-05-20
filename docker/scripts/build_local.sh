#!/bin/bash
# 构建并运行本地Docker镜像（不含敏感信息）
# 作用：构建一个不包含敏感信息的Docker镜像，并通过卷挂载方式注入敏感配置

# 设置工作目录为项目根目录
PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$PROJECT_ROOT"

echo "==== 构建本地Docker镜像（不含敏感信息）===="
echo "工作目录: $PROJECT_ROOT"

# 构建镜像
echo "构建镜像..."
docker build -f docker/dockerfiles/Dockerfile-server -t xiaozhi-esp32-server:clean .

# 检查构建是否成功
if [ $? -ne 0 ]; then
    echo "镜像构建失败，请检查日志"
    exit 1
fi

echo "镜像构建成功: xiaozhi-esp32-server:clean"

# 启动容器
echo "使用docker-compose启动服务..."
docker-compose -f docker/compose/docker-compose.local.yml up -d

# 检查启动是否成功
if [ $? -ne 0 ]; then
    echo "服务启动失败，请检查日志"
    exit 1
fi

echo "服务已成功启动"
echo "WebSocket服务端口: 8000"
echo "角色API服务端口: 8081"
echo ""
echo "查看日志: docker logs xiaozhi-esp32-server-local"
echo "停止服务: docker-compose -f docker/compose/docker-compose.local.yml down"
