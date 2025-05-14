import os
import json
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

class RoleStorage:
    """角色数据存储类，负责角色数据的读写操作"""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """单例模式，确保只有一个RoleStorage实例"""
        if cls._instance is None:
            cls._instance = RoleStorage()
        return cls._instance
    
    def __init__(self, storage_path=None):
        """初始化角色存储
        
        Args:
            storage_path: 角色数据存储路径，默认为data/roles.json
        """
        self.roles = {}
        self.default_role_id = None
        
        # 设置存储路径
        if storage_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.storage_path = os.path.join(base_dir, 'data', 'roles.json')
        else:
            self.storage_path = storage_path
            
        # 确保目录存在
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        
        # 加载角色数据
        self._load_roles()
    
    def _load_roles(self):
        """从文件加载角色数据"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 兼容两种格式：
                    # 1. 直接字典形式：{"role_id": {...}, "role_id2": {...}}
                    # 2. 带roles和default_role_id的形式：{"roles": {...}, "default_role_id": "..."}
                    if 'roles' in data:
                        logger.bind(tag=TAG).info("使用带roles结构的JSON格式加载角色数据")
                        self.roles = data.get('roles', {})
                        self.default_role_id = data.get('default_role_id')
                    else:
                        logger.bind(tag=TAG).info("使用直接字典的JSON格式加载角色数据")
                        self.roles = data
                        # 查找集默认角色
                        for role_id, role_data in self.roles.items():
                            if role_data.get("is_default", False):
                                self.default_role_id = role_id
                                break
                                
                    logger.bind(tag=TAG).info(f"从 {self.storage_path} 加载了 {len(self.roles)} 个角色")
                    logger.bind(tag=TAG).info(f"角色列表: {list(self.roles.keys())}")
                    logger.bind(tag=TAG).info(f"默认角色ID: {self.default_role_id}")
            else:
                logger.bind(tag=TAG).info(f"角色数据文件 {self.storage_path} 不存在，将创建默认角色")
                self._initialize_default_roles()
        except Exception as e:
            logger.bind(tag=TAG).error(f"加载角色数据失败: {e}")
            self._initialize_default_roles()
    
    def _initialize_default_roles(self):
        """初始化默认角色数据"""
        # 从config.yaml获取默认prompt
        try:
            from config.settings import load_config
            config = load_config()
            default_prompt = config.get("prompt", "")
            
            # 添加默认角色
            self.roles["default"] = {
                "name": "默认角色",
                "description": "小智/小志，台湾女生",
                "prompt": default_prompt,
                "voice": "zh-CN-XiaoxiaoNeural"
            }
            self.default_role_id = "default"
            
            # 从change_role.py获取预设角色
            try:
                from plugins_func.functions.change_role import prompts
                
                for role_name, prompt in prompts.items():
                    role_id = role_name.lower().replace(' ', '_')
                    self.roles[role_id] = {
                        "name": role_name,
                        "description": f"{role_name}角色",
                        "prompt": prompt,
                        "voice": "zh-CN-XiaoxiaoNeural"
                    }
            except Exception as e:
                logger.bind(tag=TAG).error(f"加载预设角色失败: {e}")
            
            # 保存初始化的角色数据
            self._save_roles()
            logger.bind(tag=TAG).info(f"初始化了 {len(self.roles)} 个默认角色")
        except Exception as e:
            logger.bind(tag=TAG).error(f"初始化默认角色失败: {e}")
    
    def _save_roles(self):
        """保存角色数据到文件"""
        try:
            # 直接保存角色字典，不再使用roles嵌套结构
            # 如果有默认角色，确保它的is_default属性设置为True
            if self.default_role_id:
                for role_id, role_data in self.roles.items():
                    role_data["is_default"] = (role_id == self.default_role_id)
            
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self.roles, f, ensure_ascii=False, indent=2)
                
            logger.bind(tag=TAG).info(f"角色数据已保存到 {self.storage_path}, 共{len(self.roles)}个角色")
            logger.bind(tag=TAG).info(f"默认角色ID: {self.default_role_id}")
        except Exception as e:
            logger.bind(tag=TAG).error(f"保存角色数据失败: {e}")
    
    def get_all_roles(self):
        """获取所有角色"""
        return self.roles
    
    def get_role(self, role_id):
        """获取指定角色"""
        return self.roles.get(role_id)
    
    def get_role_by_name(self, name):
        """通过名称获取角色"""
        for role_id, role_data in self.roles.items():
            if role_data.get('name') == name:
                return role_id, role_data
        return None, None
    
    def get_default_role(self):
        """获取默认角色"""
        if self.default_role_id and self.default_role_id in self.roles:
            return self.default_role_id, self.roles[self.default_role_id]
        return None, None
    
    def add_role(self, role_id, role_data):
        """添加角色"""
        self.roles[role_id] = role_data
        self._save_roles()
        return role_data
    
    def update_role(self, role_id, role_data):
        """更新角色"""
        if role_id not in self.roles:
            return None
        
        self.roles[role_id] = role_data
        self._save_roles()
        return role_data
    
    def delete_role(self, role_id):
        """删除角色"""
        if role_id not in self.roles:
            return False
        
        # 不允许删除默认角色
        if role_id == self.default_role_id:
            return False
        
        del self.roles[role_id]
        self._save_roles()
        return True
    
    def set_default_role(self, role_id):
        """设置默认角色"""
        if role_id not in self.roles:
            return False
        
        self.default_role_id = role_id
        self._save_roles()
        return True
