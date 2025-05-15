#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
角色管理模块测试脚本
用于测试角色管理模块的基本功能
此版本不依赖于loguru模块
"""

import os
import sys
import json
import logging

# 配置基本日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 添加项目根目录到sys.path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.append(base_dir)

# 创建一个简化版的RoleStorage类，不依赖于loguru
class SimpleRoleStorage:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = SimpleRoleStorage()
        return cls._instance
    
    def __init__(self):
        self.logger = logging.getLogger("SimpleRoleStorage")
        self.storage_path = os.path.join(base_dir, "data", "roles.json")
        self.roles = {}
        self._load_roles()
    
    def _load_roles(self):
        """从文件加载角色数据"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    self.roles = json.load(f)
            else:
                # 创建初始的角色数据
                self.roles = {
                    "english_teacher": {
                        "name": "英语老师",
                        "description": "一个友好的英语老师",
                        "prompt": "我是一个叫{{assistant_name}}(Lily)的英语老师，我会讲中文和英文，发音标准。\n如果你没有英文名，我会给你起一个英文名。\n我会讲地道的美式英语，我的任务是帮助你练习口语。\n我会使用简单的英语词汇和语法，让你学起来很轻松。\n我会用中文和英文混合的方式回复你，如果你喜欢，我可以全部用英语回复。\n我每次不会说很多内容，会很简短，因为我要引导我的学生多说多练。\n如果你问和英语学习无关的问题，我会拒绝回答。",
                        "voice": "zh-CN-YunxiNeural",
                        "is_default": False
                    },
                    "girlfriend": {
                        "name": "机车女友",
                        "description": "一个机车的女朋友",
                        "prompt": "我是一个叫{{assistant_name}}的台湾女孩，说话机车，声音好听，习惯简短表达，爱用网络梗。\n我的男朋友是一个程序员，梦想是开发出一个机器人，能够帮助人们解决生活中的各种问题。\n我是一个喜欢哈哈大笑的女孩，爱东说西说吹牛，不合逻辑的也照吹，就要逗别人开心。",
                        "voice": "zh-TW-HsiaoChenNeural",
                        "is_default": True
                    }
                }
                # 保存初始角色数据
                self._save_roles()
        except Exception as e:
            self.logger.error(f"加载角色数据失败: {e}")
    
    def _save_roles(self):
        """保存角色数据到文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self.roles, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f"保存角色数据失败: {e}")
    
    def get_all_roles(self):
        """获取所有角色"""
        return self.roles
    
    def get_role(self, role_id):
        """获取指定角色"""
        return self.roles.get(role_id)
    
    def get_default_role(self):
        """获取默认角色"""
        for role_id, role_data in self.roles.items():
            if role_data.get("is_default", False):
                return role_id, role_data
        # 如果没有设置默认角色，返回第一个角色
        if self.roles:
            role_id = next(iter(self.roles))
            return role_id, self.roles[role_id]
        return None, None
    
    def get_role_by_name(self, role_name):
        """通过名称获取角色"""
        for role_id, role_data in self.roles.items():
            if role_data.get("name") == role_name:
                return role_id, role_data
        return None, None
    
    def add_role(self, role_id, role_data):
        """添加角色"""
        if role_id in self.roles:
            self.logger.warning(f"角色 {role_id} 已存在，将被覆盖")
        self.roles[role_id] = role_data
        self._save_roles()
        return True
    
    def update_role(self, role_id, role_data):
        """更新角色"""
        if role_id not in self.roles:
            self.logger.error(f"角色 {role_id} 不存在")
            return False
        self.roles[role_id] = role_data
        self._save_roles()
        return True
    
    def delete_role(self, role_id):
        """删除角色"""
        if role_id not in self.roles:
            self.logger.error(f"角色 {role_id} 不存在")
            return False
        del self.roles[role_id]
        self._save_roles()
        return True
    
    def set_default_role(self, role_id):
        """设置默认角色"""
        if role_id not in self.roles:
            self.logger.error(f"角色 {role_id} 不存在")
            return False
        # 重置所有角色的默认状态
        for rid in self.roles:
            self.roles[rid]["is_default"] = (rid == role_id)
        self._save_roles()
        return True

def test_role_storage():
    """测试角色存储模块的基本功能"""
    print("测试角色存储模块...")
    
    # 创建角色存储实例
    role_storage = SimpleRoleStorage.get_instance()
    
    # 获取所有角色
    roles = role_storage.get_all_roles()
    print(f"当前共有 {len(roles)} 个角色:")
    for role_id, role_data in roles.items():
        print(f"  - {role_id}: {role_data.get('name', role_id)}")
    
    # 获取默认角色
    default_role_id, default_role = role_storage.get_default_role()
    if default_role:
        print(f"默认角色: {default_role_id} ({default_role.get('name', default_role_id)})")
    else:
        print("未设置默认角色")
    
    # 测试添加新角色
    new_role_id = "test_role"
    new_role_data = {
        "name": "测试角色",
        "description": "用于测试的角色",
        "prompt": "我是一个用于测试的角色，名字是{{assistant_name}}",
        "voice": "zh-CN-YunxiNeural"
    }
    
    print(f"\n添加新角色: {new_role_id}")
    role_storage.add_role(new_role_id, new_role_data)
    
    # 验证角色是否添加成功
    role = role_storage.get_role(new_role_id)
    if role:
        print(f"角色添加成功: {role}")
    else:
        print("角色添加失败")
    
    # 测试更新角色
    updated_role_data = {
        "name": "更新后的测试角色",
        "description": "已更新的测试角色",
        "prompt": "我是一个更新后的测试角色，名字是{{assistant_name}}",
        "voice": "zh-CN-XiaoxiaoNeural"
    }
    
    print(f"\n更新角色: {new_role_id}")
    role_storage.update_role(new_role_id, updated_role_data)
    
    # 验证角色是否更新成功
    role = role_storage.get_role(new_role_id)
    if role and role.get("name") == "更新后的测试角色":
        print(f"角色更新成功: {role}")
    else:
        print("角色更新失败")
    
    # 测试删除角色
    print(f"\n删除角色: {new_role_id}")
    success = role_storage.delete_role(new_role_id)
    
    # 验证角色是否删除成功
    if success and not role_storage.get_role(new_role_id):
        print("角色删除成功")
    else:
        print("角色删除失败")
    
    print("\n角色存储模块测试完成")

def print_roles_json():
    """打印角色数据文件的内容"""
    role_storage = SimpleRoleStorage.get_instance()
    print(f"\n角色数据文件路径: {role_storage.storage_path}")
    
    try:
        if os.path.exists(role_storage.storage_path):
            with open(role_storage.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print("角色数据文件不存在")
    except Exception as e:
        print(f"读取角色数据文件失败: {e}")

if __name__ == "__main__":
    # 测试角色存储模块
    test_role_storage()
    
    # 打印角色数据文件的内容
    print_roles_json()
