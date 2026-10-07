"""Roda 1 comando no servidor de homologação via SSH (ver DEPLOY_RAPIDO.md).

Lê IP/usuário/senha de ServidorEACE.md (raiz do repositório, fora do git) e
nunca imprime a senha. Uso:

    python scripts/ssh_eace.py "cd /home/Sistem_PosVenda && git log --oneline -1"
"""

import re
import sys
from pathlib import Path

import paramiko

RAIZ = Path(__file__).resolve().parent.parent
texto = (RAIZ / "ServidorEACE.md").read_text(encoding="utf-8")
ip = re.search(r"IP:\s*(\S+)", texto).group(1)
usuario = re.search(r"SSH\s*\nIP:.*\nUsuario:\s*(\S+)", texto).group(1)
senha = re.search(r"Ssenha:\s*(.+)", texto).group(1).strip()

cliente = paramiko.SSHClient()
cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cliente.connect(ip, username=usuario, password=senha, timeout=20, look_for_keys=False, allow_agent=False)
_, stdout, stderr = cliente.exec_command(sys.argv[1], timeout=1800)
saida = stdout.read().decode("utf-8", "replace")
erro = stderr.read().decode("utf-8", "replace")
codigo = stdout.channel.recv_exit_status()
sys.stdout.write(saida.replace(senha, "***"))
if erro:
    sys.stdout.write("\n[stderr]\n" + erro.replace(senha, "***"))
sys.stdout.write(f"\n[exit {codigo}]\n")
cliente.close()
sys.exit(codigo)
