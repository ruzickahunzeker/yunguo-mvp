"""Create one local acceptance admin; store credentials outside the source tree.
Run manually against a local development Compose deployment. Never logs secrets.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
from uuid import uuid4
import httpx

ROOT=Path(__file__).resolve().parents[1]
TARGET=Path(os.environ.get('ACCEPTANCE_FILE',str(ROOT.parent/'yunguo-mvp-acceptance.txt')))
BASE_URL=os.environ.get('ACCEPTANCE_BASE_URL','http://127.0.0.1:8080')

def main():
    with httpx.Client(base_url=BASE_URL,timeout=10) as client:
        health=client.get('/api/health')
        health.raise_for_status()
        if not health.json().get('demo'):
            raise RuntimeError('Acceptance credentials are only for the disposable local demo stack')
        if TARGET.exists():
            raise RuntimeError('Acceptance credential file exists; refusing to create another account or overwrite it')
        email=f'acceptance-{uuid4().hex[:10]}@example.com'
        password=secrets.token_urlsafe(24)
        script="""
import json,os,sys
from app.cli import main
payload=json.loads(sys.stdin.read())
os.environ['ADMIN_PASSWORD']=payload['password']
sys.argv=['cli','create-admin','--email',payload['email']]
main()
"""
        fd=os.open(TARGET,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            subprocess.run(['docker','compose','exec','-T','api','python','-c',script],
                cwd=ROOT,input=json.dumps({'email':email,'password':password}),text=True,capture_output=True,check=True)
            result=client.post('/api/auth/login',json={'email':email,'password':password})
            assert result.status_code==200 and result.json()['user']['role']=='admin'
            token=result.json()['access_token']
            assert client.get('/api/admin/operations/monitor',headers={'Authorization':'Bearer '+token}).status_code==200
            client.post('/api/auth/logout',headers={'Authorization':'Bearer '+token}).raise_for_status()
            body=f'''云果本机验收账号（请妥善保管，文件权限0600）
访问：{BASE_URL}
邮箱：{email}
密码：{password}
角色：管理员
此实例仅供本机演示/验收，不提供真实支付或外部订阅开通。
已检查登录和管理员接口，检查会话已退出。
验收后可通过受控CLI修改密码并删除此凭据文件。
'''
            with os.fdopen(fd,'w') as file:
                fd=None
                file.write(body)
        except BaseException:
            if fd is not None:os.close(fd)
            TARGET.unlink(missing_ok=True)
            raise
    print('Local acceptance administrator ready; credentials saved outside source archive with mode 0600')

if __name__=='__main__':
    main()
