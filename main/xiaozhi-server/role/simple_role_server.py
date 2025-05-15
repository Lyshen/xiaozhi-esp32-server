#!/usr/bin/env python3
"""
简单角色管理API服务器
使用Python内置HTTP模块，不依赖Flask
"""

import os
import sys
import json
import threading
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs

# 添加项目根目录到PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入角色存储模块
from role.role_storage import RoleStorage

# 初始化角色存储
role_storage = RoleStorage.get_instance()

class RoleAPIHandler(http.server.BaseHTTPRequestHandler):
    """简单的角色API请求处理器"""
    
    def _set_headers(self, status_code=200, content_type='application/json'):
        """设置响应头"""
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')  # 允许跨域
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        
    def do_OPTIONS(self):
        """处理OPTIONS请求（跨域预检）"""
        self._set_headers()
        
    def do_GET(self):
        """处理GET请求"""
        url = urlparse(self.path)
        path = url.path
        
        # 健康检查
        if path == '/health':
            self._set_headers()
            response = {'status': 'ok', 'service': 'role-api'}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        # 获取所有角色
        if path == '/api/roles':
            self._set_headers()
            roles = role_storage.get_all_roles()
            response = {'roles': roles}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        # 获取默认角色
        if path == '/api/roles/default':
            self._set_headers()
            role_id, role = role_storage.get_default_role()
            if not role:
                self._set_headers(404)
                response = {'error': '未设置默认角色'}
            else:
                response = {'id': role_id, 'role': role}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        # 获取指定角色
        if path.startswith('/api/roles/') and not path.endswith('/default'):
            role_id = path.split('/')[-1]
            role = role_storage.get_role(role_id)
            if not role:
                self._set_headers(404)
                response = {'error': '角色不存在'}
            else:
                self._set_headers()
                response = {'role': role}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        # 其他路径
        self._set_headers(404)
        response = {'error': '未找到请求的资源'}
        self.wfile.write(json.dumps(response).encode('utf-8'))
        
    def do_POST(self):
        """处理POST请求"""
        url = urlparse(self.path)
        path = url.path
        
        # 读取请求体
        content_length = int(self.headers.get('Content-Length', 0))
        request_body = self.rfile.read(content_length).decode('utf-8')
        request_data = {}
        if request_body:
            try:
                request_data = json.loads(request_body)
            except json.JSONDecodeError:
                self._set_headers(400)
                response = {'error': '无效的JSON数据'}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return
        
        # 创建新角色
        if path == '/api/roles':
            if not request_data or 'name' not in request_data or 'prompt' not in request_data:
                self._set_headers(400)
                response = {'error': '缺少必要参数'}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return
                
            role_id = request_data.pop('id', None)
            if not role_id:
                role_id = request_data['name'].lower().replace(' ', '_')
                
            if role_storage.get_role(role_id):
                self._set_headers(400)
                response = {'error': f"角色ID '{role_id}' 已存在"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return
                
            new_role = role_storage.add_role(role_id, request_data)
            self._set_headers(201)
            response = {'id': role_id, 'role': new_role}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        # 设置默认角色
        if path.endswith('/default'):
            role_id = path.split('/')[-2]
            success = role_storage.set_default_role(role_id)
            if not success:
                self._set_headers(404)
                response = {'error': '角色不存在'}
            else:
                self._set_headers()
                response = {'success': True}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        # 其他路径
        self._set_headers(404)
        response = {'error': '未找到请求的资源'}
        self.wfile.write(json.dumps(response).encode('utf-8'))
        
    def do_PUT(self):
        """处理PUT请求"""
        url = urlparse(self.path)
        path = url.path
        
        # 读取请求体
        content_length = int(self.headers.get('Content-Length', 0))
        request_body = self.rfile.read(content_length).decode('utf-8')
        request_data = {}
        if request_body:
            try:
                request_data = json.loads(request_body)
            except json.JSONDecodeError:
                self._set_headers(400)
                response = {'error': '无效的JSON数据'}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return
        
        # 更新指定角色
        if path.startswith('/api/roles/'):
            role_id = path.split('/')[-1]
            if not request_data:
                self._set_headers(400)
                response = {'error': '缺少必要参数'}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return
                
            updated_role = role_storage.update_role(role_id, request_data)
            if not updated_role:
                self._set_headers(404)
                response = {'error': '角色不存在'}
            else:
                self._set_headers()
                response = {'id': role_id, 'role': updated_role}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        # 其他路径
        self._set_headers(404)
        response = {'error': '未找到请求的资源'}
        self.wfile.write(json.dumps(response).encode('utf-8'))
        
    def do_DELETE(self):
        """处理DELETE请求"""
        url = urlparse(self.path)
        path = url.path
        
        # 删除指定角色
        if path.startswith('/api/roles/'):
            role_id = path.split('/')[-1]
            success = role_storage.delete_role(role_id)
            if not success:
                self._set_headers(400)
                response = {'error': '角色不存在或不能删除默认角色'}
            else:
                self._set_headers()
                response = {'success': True}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        # 其他路径
        self._set_headers(404)
        response = {'error': '未找到请求的资源'}
        self.wfile.write(json.dumps(response).encode('utf-8'))

def run_server(port=8081):
    """运行HTTP服务器"""
    handler = RoleAPIHandler
    
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
    
    with ThreadedHTTPServer(("0.0.0.0", port), handler) as httpd:
        print(f"角色管理API服务器运行在端口: {port}")
        print(f"API地址: http://localhost:{port}/api/roles")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("服务器关闭")
        finally:
            httpd.server_close()

def start_server_in_thread(port=8081):
    """在后台线程中启动服务器"""
    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()
    print(f"角色管理API服务器已在后台线程启动，端口: {port}")
    return server_thread

if __name__ == "__main__":
    run_server()
