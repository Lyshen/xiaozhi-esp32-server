#!/bin/bash
# K8s部署镜像构建脚本
# 此脚本构建一个用于K8s部署的Docker镜像，不包含任何敏感信息

# 设置工作目录为项目根目录
PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$PROJECT_ROOT"

# 设置参数
IMAGE_NAME=${1:-"xiaozhi-esp32-server"}
TAG=${2:-"k8s"}

# 提示用户输入正确的镜像仓库地址
echo "请输入镜像仓库地址(例如: ghcr.io/lyshen 或 docker.io/lyshen)"
read -p "镜像仓库[默认: ghcr.io/lyshen]: " REGISTRY_INPUT
REGISTRY=${REGISTRY_INPUT:-"ghcr.io/lyshen"}

echo "==== 构建K8s部署Docker镜像 ===="
echo "工作目录: $PROJECT_ROOT"
echo "镜像名称: $REGISTRY/$IMAGE_NAME:$TAG"

# 构建镜像
echo "构建镜像..."
docker build -f docker/dockerfiles/Dockerfile-server -t $REGISTRY/$IMAGE_NAME:$TAG .

# 检查构建是否成功
if [ $? -ne 0 ]; then
    echo "镜像构建失败，请检查日志"
    exit 1
fi

echo "镜像构建成功: $REGISTRY/$IMAGE_NAME:$TAG"

# 询问是否推送镜像到仓库
read -p "是否推送镜像到仓库? (y/n): " PUSH_IMAGE
if [[ $PUSH_IMAGE == "y" || $PUSH_IMAGE == "Y" ]]; then
    echo "推送镜像到仓库..."
    docker push $REGISTRY/$IMAGE_NAME:$TAG
    
    if [ $? -ne 0 ]; then
        echo "镜像推送失败，请检查登录状态和网络连接"
        exit 1
    fi
    
    echo "镜像已成功推送到: $REGISTRY/$IMAGE_NAME:$TAG"
else
    echo "已跳过推送镜像"
fi

echo ""
echo "K8s部署准备完成"
echo "接下来请执行: ./docker/scripts/deploy_to_k8s.sh"
