from flask import Blueprint, request, jsonify
from role.role_storage import RoleStorage
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

role_api = Blueprint('role_api', __name__)
role_storage = RoleStorage.get_instance()

@role_api.route('/api/roles', methods=['GET'])
def get_roles():
    """获取所有角色列表"""
    return jsonify(roles=role_storage.get_all_roles())

@role_api.route('/api/roles/<role_id>', methods=['GET'])
def get_role(role_id):
    """获取指定角色详情"""
    role = role_storage.get_role(role_id)
    if not role:
        return jsonify(error="角色不存在"), 404
    return jsonify(role=role)

@role_api.route('/api/roles', methods=['POST'])
def create_role():
    """创建新角色"""
    role_data = request.json
    if not role_data or 'name' not in role_data or 'prompt' not in role_data:
        return jsonify(error="缺少必要参数"), 400
    
    role_id = role_data.pop('id', None)
    if not role_id:
        # 如果没有提供ID，使用名称生成ID
        role_id = role_data['name'].lower().replace(' ', '_')
    
    # 检查角色是否已存在
    if role_storage.get_role(role_id):
        return jsonify(error=f"角色ID '{role_id}' 已存在"), 400
    
    new_role = role_storage.add_role(role_id, role_data)
    return jsonify(id=role_id, role=new_role), 201

@role_api.route('/api/roles/<role_id>', methods=['PUT'])
def update_role(role_id):
    """更新指定角色"""
    role_data = request.json
    if not role_data:
        return jsonify(error="缺少必要参数"), 400
    
    updated_role = role_storage.update_role(role_id, role_data)
    if not updated_role:
        return jsonify(error="角色不存在"), 404
    return jsonify(id=role_id, role=updated_role)

@role_api.route('/api/roles/<role_id>', methods=['DELETE'])
def delete_role(role_id):
    """删除指定角色"""
    success = role_storage.delete_role(role_id)
    if not success:
        return jsonify(error="角色不存在或不能删除默认角色"), 400
    return jsonify(success=True)

@role_api.route('/api/roles/<role_id>/default', methods=['POST'])
def set_default_role(role_id):
    """设置默认角色"""
    success = role_storage.set_default_role(role_id)
    if not success:
        return jsonify(error="角色不存在"), 404
    return jsonify(success=True)

@role_api.route('/api/roles/default', methods=['GET'])
def get_default_role():
    """获取默认角色"""
    role_id, role = role_storage.get_default_role()
    if not role:
        return jsonify(error="未设置默认角色"), 404
    return jsonify(id=role_id, role=role)

def register_api(app):
    """注册API到Flask应用"""
    app.register_blueprint(role_api)
    logger.bind(tag=TAG).info("角色API已注册")
