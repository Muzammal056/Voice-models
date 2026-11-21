"""Create private environment settings without recording a plaintext password."""
import getpass,hashlib,secrets,sys
from pathlib import Path

def main():
    destination=Path(sys.argv[1] if len(sys.argv)>1 else 'app.env')
    if destination.exists():raise SystemExit('Settings already exist; choose another output path.')
    password=getpass.getpass('New admin password (12 or more characters): ')
    if len(password)<12:raise SystemExit('Choose a longer password.')
    if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords did not match.')
    salt=secrets.token_hex(12)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()
    content=f'VOICE_SESSION_SECRET={secrets.token_hex(32)}\nVOICE_PASSWORD_HASH=pbkdf2:sha256:600000${salt}${digest}\nVOICE_HTTPS=1\n'
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x',encoding='utf-8') as stream:stream.write(content)
    destination.chmod(0o600)
    print('Private settings saved. Username: admin')

if __name__=='__main__':main()
