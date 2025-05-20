#!/bin/bash
# 构建多架构支持的Docker镜像

# 确定镜像名称
DEFAULT_REGISTRY="ghcr.io/lyshen"
echo "请输入Docker镜像注册表地址 (默认: $DEFAULT_REGISTRY):"
read DOCKER_REGISTRY
DOCKER_REGISTRY=${DOCKER_REGISTRY:-$DEFAULT_REGISTRY}

# 版本号
VERSION="k8s"
IMAGE_NAME="$DOCKER_REGISTRY/xiaozhi-esp32-server:$VERSION"

# 当前目录
CURRENT_DIR=$(pwd)
PROJECT_ROOT="$CURRENT_DIR"

echo "=== 开始构建多架构镜像 ==="
echo "镜像名称: $IMAGE_NAME"
echo "项目路径: $PROJECT_ROOT"

# 启用 buildx
docker buildx create --use --name multi-arch-builder

# 构建并推送多架构镜像
docker buildx build --platform linux/amd64,linux/arm64 \
  -t $IMAGE_NAME \
  -f "$PROJECT_ROOT/docker/dockerfiles/Dockerfile-server" \
  --push \
  $PROJECT_ROOT

echo "=== 构建完成 ==="
echo "多架构镜像已构建并推送至: $IMAGE_NAME"
