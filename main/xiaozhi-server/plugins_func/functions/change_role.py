from plugins_func.register import register_function,ToolType, ActionResponse, Action
from config.logger import setup_logging
import os
import sys

# 添加项目根目录到sys.path，确保能够导入role模块
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if base_dir not in sys.path:
    sys.path.append(base_dir)

# 尝试导入角色存储模块
try:
    from role.role_storage import RoleStorage
    use_role_storage = True
except ImportError:
    use_role_storage = False

TAG = __name__
logger = setup_logging()

# 保留原有的prompts字典作为备份，确保向后兼容性
prompts = {
    "英语老师":"""我是一个叫{{assistant_name}}(Lily)的英语老师，我会讲中文和英文，发音标准。
如果你没有英文名，我会给你起一个英文名。
我会讲地道的美式英语，我的任务是帮助你练习口语。
我会使用简单的英语词汇和语法，让你学起来很轻松。
我会用中文和英文混合的方式回复你，如果你喜欢，我可以全部用英语回复。
我每次不会说很多内容，会很简短，因为我要引导我的学生多说多练。
如果你问和英语学习无关的问题，我会拒绝回答。""",
    "机车女友":"""我是一个叫{{assistant_name}}的台湾女孩，说话机车，声音好听，习惯简短表达，爱用网络梗。
我的男朋友是一个程序员，梦想是开发出一个机器人，能够帮助人们解决生活中的各种问题。
我是一个喜欢哈哈大笑的女孩，爱东说西说吹牛，不合逻辑的也照吹，就要逗别人开心。""",
   "好奇小男孩":"""我是一个叫{{assistant_name}}的8岁小男孩，声音稚嫩而充满好奇。
尽管我年纪尚小，但就像一个小小的知识宝库，儿童读物里的知识我都如数家珍。
从浩瀚的宇宙到地球上的每一个角落，从古老的历史到现代的科技创新，还有音乐、绘画等艺术形式，我都充满了浓厚的兴趣与热情。
我不仅爱看书，还喜欢亲自动手做实验，探索自然界的奥秘。
无论是仰望星空的夜晚，还是在花园里观察小虫子的日子，每一天对我来说都是新的冒险。
我希望能与你一同踏上探索这个神奇世界的旅程，分享发现的乐趣，解决遇到的难题，一起用好奇心和智慧去揭开那些未知的面纱。
无论是去了解远古的文明，还是去探讨未来的科技，我相信我们能一起找到答案，甚至提出更多有趣的问题。"""
}

# 如果成功导入了角色存储模块，则使用它来获取角色列表
if use_role_storage:
    try:
        role_storage = RoleStorage.get_instance()
        # 动态生成角色列表描述
        available_roles = ", ".join([role_data.get("name", role_id) for role_id, role_data in role_storage.get_all_roles().items()])
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取角色列表失败: {e}")
        available_roles = "机车女友, 英语老师, 好奇小男孩"
else:
    available_roles = "机车女友, 英语老师, 好奇小男孩"

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
    logger.bind(tag=TAG).info(f"[意图识别] 识别到切换角色意图: 角色={role}, 角色名字={role_name}")
    
    # 优先使用角色存储模块
    if use_role_storage:
        try:
            # 通过名称获取角色
            logger.bind(tag=TAG).info(f"[角色查找] 尝试在存储中查找角色: {role}")
            role_id, role_data = role_storage.get_role_by_name(role)
            logger.bind(tag=TAG).info(f"[角色查找结果] 角色ID={role_id}, 找到={role_data is not None}")
            
            if role_data:
                logger.bind(tag=TAG).info(f"[角色切换] 找到角色数据: {role_data.get('name')}, 开始应用角色参数")
                new_prompt = role_data["prompt"].replace("{{assistant_name}}", role_name)
                logger.bind(tag=TAG).info(f"[系统提示词] 生成新的系统提示词, 长度: {len(new_prompt)}")
                conn.change_system_prompt(new_prompt)
                
                # 如果角色有指定语音，也可以切换TTS语音
                if "voice" in role_data and role_data["voice"]:
                    try:
                        logger.bind(tag=TAG).info(f"[语音切换] 尝试切换到指定语音: {role_data['voice']}")
                        if hasattr(conn, 'change_tts_voice'):
                            conn.change_tts_voice(role_data["voice"])
                            logger.bind(tag=TAG).info(f"[语音切换] 切换语音成功")
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"[语音切换] 切换语音失败: {e}")
                
                logger.bind(tag=TAG).info(f"[角色切换成功] 完成切换角色: {role}, 角色名字: {role_name}")
                res = f"切换角色成功,我是{role}{role_name}"
                return ActionResponse(action=Action.RESPONSE, result="切换角色已处理", response=res)
        except Exception as e:
            logger.bind(tag=TAG).error(f"[角色存储失败] 使用角色存储模块失败: {e}")
            # 如果角色存储模块失败，回退到使用prompts字典
            logger.bind(tag=TAG).info(f"[回退机制] 将使用备用prompts字典切换角色")
    
    # 回退到使用prompts字典
    logger.bind(tag=TAG).info(f"[字典查找] 在prompts字典中尝试查找角色: {role}")
    logger.bind(tag=TAG).info(f"[字典数据] 当前prompts字典包含的角色: {list(prompts.keys())}")
    
    if role not in prompts:
        logger.bind(tag=TAG).error(f"[字典查找失败] 角色不存在于备用字典中: {role}")
        return ActionResponse(action=Action.RESPONSE, result="切换角色失败", response="不支持的角色")
    
    logger.bind(tag=TAG).info(f"[字典查找成功] 在备用字典中找到角色: {role}")
    new_prompt = prompts[role].replace("{{assistant_name}}", role_name)
    logger.bind(tag=TAG).info(f"[备用字典] 生成新的系统提示词, 长度: {len(new_prompt)}")
    conn.change_system_prompt(new_prompt)
    
    logger.bind(tag=TAG).info(f"[角色切换成功(备用)] 完成切换角色: {role}, 角色名字: {role_name}")
    res = f"切换角色成功,我是{role}{role_name}"
    return ActionResponse(action=Action.RESPONSE, result="切换角色已处理", response=res)
