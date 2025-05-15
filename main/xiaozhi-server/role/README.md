# 角色管理模块

## 概述

该模块用于管理角色数据，包括角色的配置、提示词和语音设置。它将原本硬编码在代码中的角色提示词转化为可通过API动态管理的数据。

## 模块结构

```
role/
├── __init__.py       # 模块初始化
├── role_storage.py   # 角色数据存储类
├── role_api.py       # 角色HTTP API接口
├── role_server.py    # 用于测试的HTTP服务器
└── README.md         # 模块说明文档
```

## 数据存储

角色数据存储在 `data/roles.json` 文件中，格式如下：

```json
{
  "roles": {
    "default": {
      "name": "默认角色",
      "description": "小智/小志，台湾女生",
      "prompt": "我是小智/小志，来自中国台湾省...",
      "voice": "zh-CN-XiaoxiaoNeural"
    },
    "english_teacher": {
      "name": "英语老师",
      "description": "英语教学助手",
      "prompt": "我是一个叫{{assistant_name}}(Lily)的英语老师...",
      "voice": "zh-CN-YunxiNeural"
    }
  },
  "default_role_id": "default"
}
```

## API 接口

### 获取所有角色

```
GET /api/roles
```

响应示例：

```json
{
  "roles": {
    "default": {
      "name": "默认角色",
      "description": "小智/小志，台湾女生",
      "prompt": "我是小智/小志，来自中国台湾省...",
      "voice": "zh-CN-XiaoxiaoNeural"
    },
    "english_teacher": {
      "name": "英语老师",
      "description": "英语教学助手",
      "prompt": "我是一个叫{{assistant_name}}(Lily)的英语老师...",
      "voice": "zh-CN-YunxiNeural"
    }
  }
}
```

### 获取指定角色

```
GET /api/roles/{role_id}
```

响应示例：

```json
{
  "role": {
    "name": "英语老师",
    "description": "英语教学助手",
    "prompt": "我是一个叫{{assistant_name}}(Lily)的英语老师...",
    "voice": "zh-CN-YunxiNeural"
  }
}
```

### 创建新角色

```
POST /api/roles
Content-Type: application/json

{
  "name": "角色名称",
  "description": "角色描述",
  "prompt": "角色提示词",
  "voice": "角色语音"
}
```

响应示例：

```json
{
  "id": "角色id",
  "role": {
    "name": "角色名称",
    "description": "角色描述",
    "prompt": "角色提示词",
    "voice": "角色语音"
  }
}
```

### 更新角色

```
PUT /api/roles/{role_id}
Content-Type: application/json

{
  "name": "角色名称",
  "description": "角色描述",
  "prompt": "角色提示词",
  "voice": "角色语音"
}
```

响应示例：

```json
{
  "id": "角色id",
  "role": {
    "name": "角色名称",
    "description": "角色描述",
    "prompt": "角色提示词",
    "voice": "角色语音"
  }
}
```

### 删除角色

```
DELETE /api/roles/{role_id}
```

响应示例：

```json
{
  "success": true
}
```

### 设置默认角色

```
POST /api/roles/{role_id}/default
```

响应示例：

```json
{
  "success": true
}
```

### 获取默认角色

```
GET /api/roles/default
```

响应示例：

```json
{
  "id": "default",
  "role": {
    "name": "默认角色",
    "description": "小智/小志，台湾女生",
    "prompt": "我是小智/小志，来自中国台湾省...",
    "voice": "zh-CN-XiaoxiaoNeural"
  }
}
```

## 与现有代码集成

要将角色管理模块集成到现有项目中，需要对 `plugins_func/functions/change_role.py` 进行最小化修改，使其使用角色管理模块：

```python
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from role.role_storage import RoleStorage  # 导入角色存储模块

TAG = __name__
logger = setup_logging()

# 获取角色存储实例
role_storage = RoleStorage.get_instance()

# 动态生成角色列表描述
available_roles = ", ".join([role_data["name"] for role_id, role_data in role_storage.get_all_roles().items()])

change_role_function_desc = {
    "type": "function",
    "function": {
        "name": "change_role",
        "description": f"当用户想切换角色/模型性格/助手名字时调用,可选的角色有：[{available_roles}]",
        "parameters": {
            "type": "object",
            "properties": {
                "role_name": {
                    "type": "string",
                    "description": "要切换的角色名字"
                },
                "role":{
                    "type": "string",
                    "description": "要切换的角色的职业"
                }
            },
            "required": ["role","role_name"]
        }
    }
}

@register_function('change_role', change_role_function_desc, ToolType.CHANGE_SYS_PROMPT)
def change_role(conn, role: str, role_name: str):
    """切换角色"""
    # 通过名称获取角色
    role_id, role_data = role_storage.get_role_by_name(role)
    if not role_data:
        return ActionResponse(action=Action.RESPONSE, result="切换角色失败", response="不支持的角色")
    
    new_prompt = role_data["prompt"].replace("{{assistant_name}}", role_name)
    conn.change_system_prompt(new_prompt)
    
    # 如果角色有指定语音，也可以切换TTS语音
    if "voice" in role_data and role_data["voice"]:
        try:
            conn.change_tts_voice(role_data["voice"])
        except:
            pass  # 忽略语音切换错误
    
    logger.bind(tag=TAG).info(f"准备切换角色:{role},角色名字:{role_name}")
    res = f"切换角色成功,我是{role}{role_name}"
    return ActionResponse(action=Action.RESPONSE, result="切换角色已处理", response=res)
```

## 启动测试服务器

要启动测试服务器，运行以下命令：

```bash
cd /path/to/xiaozhi-esp32-server/main/xiaozhi-server
python -m role.role_server
```

然后访问 http://localhost:8080 查看API文档。
