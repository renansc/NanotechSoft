#!/usr/bin/env python3
"""Assistente operacional para Git, deploy e backups do RioBranco."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shlex
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from riob_context import build_task_brief, format_task_brief

GIT_EXCLUDES = [
    ":(exclude).env",
    ":(exclude).env.*",
    ":(exclude)backupsSql/**",
    ":(exclude)sync-backups/**",
    ":(exclude)certs/**",
    ":(exclude)Relatorios/**",
    ":(exclude)cameras/cams/**",
    ":(exclude)cameras/cams.json",
    ":(exclude)cameras/*.db",
    ":(exclude)**/*.ts",
    ":(exclude)**/live.m3u8",
]

DEFAULT_SERVICES = ["app", "proxy"]
GIT_ADD_BATCH_SIZE = 50


class AgentError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[riob-agent] {message}", flush=True)


def quote_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
    read_only: bool = False,
) -> subprocess.CompletedProcess[str]:
    log(quote_cmd(cmd))
    if dry_run and not read_only:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=capture,
        env=env,
    )
    if check and result.returncode != 0:
        if capture and result.stdout:
            print(result.stdout, end="")
        if capture and result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise AgentError(f"comando falhou com codigo {result.returncode}: {quote_cmd(cmd)}")
    return result


def ask(question: str, yes: bool = False) -> bool:
    if yes:
        return True
    answer = input(f"{question} [s/N] ").strip().lower()
    return answer in {"s", "sim", "y", "yes"}


def need_program(name: str) -> None:
    if not shutil.which(name):
        raise AgentError(f"programa nao encontrado no PATH: {name}")


def docker_compose(*args: str, dry_run: bool = False, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["docker", "compose", *args], dry_run=dry_run, capture=capture)


def is_risky_git_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    return (
        normalized == ".env"
        or normalized.startswith(".env.")
        or normalized.startswith("backupsSql/")
        or normalized.startswith("sync-backups/")
        or normalized.startswith("certs/")
        or normalized.startswith("Relatorios/")
        or normalized.startswith("cameras/cams/")
        or normalized == "cameras/cams.json"
        or normalized == "cameras/cameras.db"
        or normalized.endswith(".ts")
        or name == "live.m3u8"
    )


def is_allowed_git_path(path: str) -> bool:
    return bool(path) and not is_risky_git_path(path)


def current_branch(dry_run: bool = False) -> str:
    result = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture=True,
        dry_run=dry_run,
        read_only=True,
    )
    return (result.stdout or "main").strip() or "main"


def git_changed_files(*, cached: bool = False, dry_run: bool = False) -> list[str]:
    cmd = ["git", "diff", "--name-only"]
    if cached:
        cmd = ["git", "diff", "--cached", "--name-only"]
    result = run(cmd, capture=True, dry_run=dry_run, read_only=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_worktree_changed_files(dry_run: bool = False) -> list[str]:
    result = run(
        ["git", "ls-files", "--modified", "--deleted", "--others", "--exclude-standard", "-z"],
        capture=True,
        dry_run=dry_run,
        read_only=True,
    )
    files = [item for item in result.stdout.split("\0") if item]
    return sorted(dict.fromkeys(files))


def stage_allowed_changes(args: argparse.Namespace) -> None:
    changed = git_worktree_changed_files(dry_run=args.dry_run)
    allowed = [path for path in changed if is_allowed_git_path(path)]
    blocked = [path for path in changed if not is_allowed_git_path(path)]

    if blocked:
        log(f"ignorando {len(blocked)} arquivo(s) bloqueado(s) por seguranca")
        for path in blocked[:12]:
            log(f"bloqueado: {path}")
        if len(blocked) > 12:
            log(f"... e mais {len(blocked) - 12}")

    if not allowed:
        log("nenhuma alteracao permitida nova para adicionar ao stage")
        return

    log(f"adicionando {len(allowed)} arquivo(s) permitido(s) ao stage")
    for index in range(0, len(allowed), GIT_ADD_BATCH_SIZE):
        batch = allowed[index : index + GIT_ADD_BATCH_SIZE]
        run(["git", "add", "--", *batch], dry_run=args.dry_run)


def backup_dir() -> Path:
    env = load_env()
    configured = env.get("RB_DB_BACKUP_PATH", "./backupsSql")
    path = Path(configured)
    if not path.is_absolute():
        path = ROOT / path
    return path


def latest_backup(patterns: tuple[str, ...] = ("*.sql", "*.sql.gz", "*.tar.gz")) -> Path | None:
    directory = backup_dir()
    if not directory.exists():
        return None
    backups: list[Path] = []
    for pattern in patterns:
        backups.extend(directory.glob(pattern))
    if not backups:
        return None
    return max(backups, key=lambda item: item.stat().st_mtime)


def public_base_url() -> str:
    env = load_env()
    configured = env.get("RB_PUBLIC_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")

    https_enabled = env.get("RB_ENABLE_HTTPS", "0") == "1"
    scheme = "https" if https_enabled else "http"
    port = env.get("RB_HTTPS_PORT" if https_enabled else "RB_HTTP_PORT", "443" if https_enabled else "80")
    host = env.get("RB_SERVER_NAME", "127.0.0.1")
    if host in {"_", "0.0.0.0"}:
        host = "127.0.0.1"
    return f"{scheme}://{host}:{port}".rstrip("/")


def health_check(timeout: int = 12) -> None:
    url = urllib.parse.urljoin(public_base_url() + "/", "api/status")
    log(f"validando saude em {url}")
    context = ssl._create_unverified_context() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
        database_ok = '"database":true' in body.replace(" ", "").lower()
        api_ok = '"api":true' in body.replace(" ", "").lower()
        log(f"api={'ok' if api_ok else 'verificar'} database={'ok' if database_ok else 'verificar'}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log(f"aviso: nao consegui validar /api/status agora: {exc}")


def do_status(args: argparse.Namespace) -> None:
    need_program("git")
    log("status Git")
    run(["git", "status", "--short", "--branch"], dry_run=args.dry_run)

    if shutil.which("docker"):
        log("containers principais")
        docker_compose("ps", *DEFAULT_SERVICES, dry_run=args.dry_run)
    else:
        log("docker nao encontrado; pulando status dos containers")

    last = latest_backup()
    if last:
        when = dt.datetime.fromtimestamp(last.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        log(f"ultimo backup: {last.relative_to(ROOT) if last.is_relative_to(ROOT) else last} ({when})")
    else:
        log(f"nenhum backup encontrado em {backup_dir()}")


def do_backup(args: argparse.Namespace) -> Path | None:
    need_program("docker")
    code = (
        "import urllib.request\n"
        "url='http://127.0.0.1:8080/api/backup'\n"
        "with urllib.request.urlopen(url, timeout=600) as resp:\n"
        "    name=resp.headers.get('X-Backup-File') or 'backup gerado'\n"
        "    while resp.read(1024 * 1024):\n"
        "        pass\n"
        "print(name)\n"
    )
    log("gerando backup SQL pelo container app")
    run(
        ["docker", "compose", "exec", "-T", "app", "python", "-c", code],
        dry_run=args.dry_run,
    )
    last = latest_backup(("*.sql", "*.sql.gz"))
    if last:
        try:
            shown = last.relative_to(ROOT)
        except ValueError:
            shown = last
        log(f"backup mais recente: {shown}")
    return last


def do_brief(args: argparse.Namespace) -> None:
    message = " ".join(getattr(args, "message", []) or []).strip()
    if not message:
        raise AgentError("preciso de um texto para analisar o pedido")
    brief = build_task_brief(message)
    print(format_task_brief(brief))


def project_python() -> str:
    candidate = ROOT / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def do_validate(args: argparse.Namespace) -> None:
    python = project_python()
    run([python, "-m", "compileall", "server.py", "tools", "tests"], dry_run=args.dry_run)
    run([python, "-m", "unittest", "discover", "-s", "tests", "-v"], dry_run=args.dry_run)
    result = run([python, "-m", "pip", "check"], dry_run=args.dry_run, check=False, capture=True)
    if not args.dry_run and result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        log("pip check retornou alerta; veja a saida acima")


def do_full_backup(args: argparse.Namespace) -> Path | None:
    need_program("docker")
    code = (
        "import urllib.request\n"
        "url='http://127.0.0.1:8080/api/backup/full'\n"
        "with urllib.request.urlopen(url, timeout=1200) as resp:\n"
        "    name=resp.headers.get('X-Backup-File') or 'backup completo gerado'\n"
        "    while resp.read(1024 * 1024):\n"
        "        pass\n"
        "print(name)\n"
    )
    log("gerando backup completo pelo container app")
    run(
        ["docker", "compose", "exec", "-T", "app", "python", "-c", code],
        dry_run=args.dry_run,
    )
    last = latest_backup(("backup_full_*.tar.gz",))
    if last:
        try:
            shown = last.relative_to(ROOT)
        except ValueError:
            shown = last
        log(f"backup completo mais recente: {shown}")
    return last


def ensure_no_risky_staged(args: argparse.Namespace) -> None:
    if getattr(args, "allow_risky_staged", False):
        return
    risky = [path for path in git_changed_files(cached=True, dry_run=args.dry_run) if is_risky_git_path(path)]
    if risky:
        formatted = "\n".join(f"  - {path}" for path in risky)
        raise AgentError(
            "ha arquivos sensiveis/runtime ja staged. Remova do stage ou use --allow-risky-staged:\n"
            + formatted
        )


def unstage_risky_files(args: argparse.Namespace) -> None:
    if getattr(args, "allow_risky_staged", False):
        return
    risky = [path for path in git_changed_files(cached=True, dry_run=args.dry_run) if is_risky_git_path(path)]
    if not risky:
        return
    log(f"removendo {len(risky)} arquivo(s) bloqueado(s) do stage sem apagar do disco")
    for index in range(0, len(risky), GIT_ADD_BATCH_SIZE):
        batch = risky[index : index + GIT_ADD_BATCH_SIZE]
        run(["git", "restore", "--staged", "--", *batch], dry_run=args.dry_run)


def do_git(args: argparse.Namespace) -> None:
    need_program("git")
    run(["git", "status", "--short", "--branch"], dry_run=args.dry_run)

    log("adicionando somente alteracoes permitidas ao stage")
    unstage_risky_files(args)
    stage_allowed_changes(args)
    ensure_no_risky_staged(args)

    staged = git_changed_files(cached=True, dry_run=args.dry_run)
    if not staged:
        log("nenhuma alteracao segura para commitar")
        return

    log("resumo do commit")
    run(["git", "diff", "--cached", "--stat"], dry_run=args.dry_run)

    message = args.message
    if not message:
        if args.yes:
            message = "Atualizacao operacional " + dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        else:
            message = input("Mensagem do commit: ").strip()
    if not message:
        raise AgentError("mensagem do commit vazia")

    if not ask("Confirmar commit dessas alteracoes?", args.yes):
        raise AgentError("commit cancelado")

    run(["git", "commit", "-m", message], dry_run=args.dry_run)

    if args.no_push:
        log("push pulado por --no-push")
        return

    branch = current_branch(dry_run=args.dry_run)
    if ask(f"Enviar branch {branch} para origin?", args.yes):
        run(["git", "push", "origin", branch], dry_run=args.dry_run)
    else:
        log("push cancelado")


def do_deploy(args: argparse.Namespace) -> None:
    need_program("docker")
    if not args.no_backup:
        do_backup(args)

    env = os.environ.copy()
    if args.no_cache:
        env["NO_CACHE"] = "1"

    log("aplicando deploy de app e proxy")
    run(["./up.sh"], dry_run=args.dry_run, env=env)
    if not args.skip_health and not args.dry_run:
        health_check()


def do_update(args: argparse.Namespace) -> None:
    need_program("git")
    need_program("docker")
    if not args.no_backup:
        do_backup(args)

    env = os.environ.copy()
    if args.no_cache:
        env["NO_CACHE"] = "1"

    cmd = ["./update.sh"]
    if args.branch:
        cmd.append(args.branch)
    run(cmd, dry_run=args.dry_run, env=env)
    if not args.skip_health and not args.dry_run:
        health_check()


def do_ship(args: argparse.Namespace) -> None:
    if not args.no_backup:
        do_backup(args)
    do_git(args)
    if not args.no_deploy:
        do_deploy(argparse.Namespace(**{**vars(args), "no_backup": True}))


def do_logs(args: argparse.Namespace) -> None:
    need_program("docker")
    services = args.services or DEFAULT_SERVICES
    run(["docker", "compose", "logs", f"--tail={args.tail}", *services], dry_run=args.dry_run)


def do_sync_homolog(args: argparse.Namespace) -> None:
    if not ask("Sincronizar producao para homologacao agora?", args.yes):
        raise AgentError("sincronizacao cancelada")
    run(["./deploy/sync-production-to-homolog.sh"], dry_run=args.dry_run)


def do_doctor(args: argparse.Namespace) -> None:
    for program in ["git", "docker"]:
        if shutil.which(program):
            log(f"{program}: ok")
        else:
            log(f"{program}: nao encontrado")
    log(f".env: {'ok' if (ROOT / '.env').exists() else 'nao encontrado'}")
    run(["git", "remote", "-v"], dry_run=args.dry_run)
    run(["git", "branch", "--show-current"], dry_run=args.dry_run)
    if shutil.which("docker"):
        docker_compose("config", "--quiet", dry_run=args.dry_run)
    last = latest_backup()
    log(f"ultimo backup: {last if last else 'nenhum'}")


def with_defaults(args: argparse.Namespace, **defaults: object) -> argparse.Namespace:
    values = vars(args).copy()
    for key, value in defaults.items():
        values.setdefault(key, value)
    return argparse.Namespace(**values)


def do_menu(args: argparse.Namespace) -> None:
    actions = {
        "1": ("status geral", do_status, {}),
        "2": ("gerar backup SQL", do_backup, {}),
        "3": (
            "commit + push seguro",
            do_git,
            {"message": None, "no_push": False, "allow_risky_staged": False},
        ),
        "4": (
            "backup + commit + push + deploy",
            do_ship,
            {
                "message": None,
                "no_backup": False,
                "no_deploy": False,
                "no_push": False,
                "no_cache": False,
                "skip_health": False,
                "allow_risky_staged": False,
            },
        ),
        "5": (
            "deploy app/proxy",
            do_deploy,
            {"no_backup": False, "no_cache": False, "skip_health": False},
        ),
        "6": (
            "update do GitHub + deploy",
            do_update,
            {"branch": None, "no_backup": False, "no_cache": False, "skip_health": False},
        ),
        "7": ("logs app/proxy", do_logs, {"tail": 200, "services": []}),
        "8": ("doctor", do_doctor, {}),
    }
    while True:
        print("\nRioBranco Agent")
        for key, (label, _, _) in actions.items():
            print(f"  {key}. {label}")
        print("  0. sair")
        choice = input("Escolha: ").strip()
        if choice == "0":
            return
        action = actions.get(choice)
        if not action:
            print("Opcao invalida.")
            continue
        _, handler, defaults = action
        handler(with_defaults(args, **defaults))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assistente local para Git, deploy, backup e operacao do RioBranco.",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="confirma perguntas automaticamente")
    parser.add_argument("--dry-run", action="store_true", help="mostra comandos sem executar")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="mostra Git, containers e ultimo backup").set_defaults(func=do_status)

    sub.add_parser("backup", help="gera backup SQL usando /api/backup").set_defaults(func=do_backup)
    sub.add_parser("full-backup", help="gera backup completo com banco e volumes").set_defaults(func=do_full_backup)

    brief_parser = sub.add_parser("brief", help="gera um brief curto com arquivos e fluxo sugeridos")
    brief_parser.add_argument("message", nargs="+", help="pedido a analisar")
    brief_parser.set_defaults(func=do_brief)

    sub.add_parser("validate", help="executa checks rapidos de validacao").set_defaults(func=do_validate)

    git_parser = sub.add_parser("git", help="stage seguro, commit e push")
    git_parser.add_argument("-m", "--message", help="mensagem do commit")
    git_parser.add_argument("--no-push", action="store_true", help="commita sem enviar ao origin")
    git_parser.add_argument(
        "--allow-risky-staged",
        action="store_true",
        help="permite commitar arquivos sensiveis/runtime que ja estavam staged",
    )
    git_parser.set_defaults(func=do_git)

    deploy_parser = sub.add_parser("deploy", help="gera backup e sobe app/proxy")
    deploy_parser.add_argument("--no-backup", action="store_true", help="sobe sem backup previo")
    deploy_parser.add_argument("--no-cache", action="store_true", help="rebuild sem cache")
    deploy_parser.add_argument("--skip-health", action="store_true", help="pula checagem /api/status")
    deploy_parser.set_defaults(func=do_deploy)

    update_parser = sub.add_parser("update", help="backup, git pull e deploy via update.sh")
    update_parser.add_argument("branch", nargs="?", help="branch para atualizar")
    update_parser.add_argument("--no-backup", action="store_true", help="atualiza sem backup previo")
    update_parser.add_argument("--no-cache", action="store_true", help="rebuild sem cache")
    update_parser.add_argument("--skip-health", action="store_true", help="pula checagem /api/status")
    update_parser.set_defaults(func=do_update)

    ship_parser = sub.add_parser("ship", help="backup, commit, push e deploy")
    ship_parser.add_argument("-m", "--message", help="mensagem do commit")
    ship_parser.add_argument("--no-backup", action="store_true", help="publica/deploya sem backup previo")
    ship_parser.add_argument("--no-deploy", action="store_true", help="publica sem deploy local")
    ship_parser.add_argument("--no-push", action="store_true", help="commita sem enviar ao origin")
    ship_parser.add_argument("--no-cache", action="store_true", help="rebuild sem cache")
    ship_parser.add_argument("--skip-health", action="store_true", help="pula checagem /api/status")
    ship_parser.add_argument(
        "--allow-risky-staged",
        action="store_true",
        help="permite commitar arquivos sensiveis/runtime que ja estavam staged",
    )
    ship_parser.set_defaults(func=do_ship)

    logs_parser = sub.add_parser("logs", help="mostra logs dos containers")
    logs_parser.add_argument("--tail", type=int, default=200, help="linhas por servico")
    logs_parser.add_argument("services", nargs="*", help="servicos docker compose")
    logs_parser.set_defaults(func=do_logs)

    sub.add_parser("sync-homolog", help="executa sync producao -> homologacao").set_defaults(func=do_sync_homolog)
    sub.add_parser("doctor", help="verifica dependencias e compose").set_defaults(func=do_doctor)
    sub.add_parser("menu", help="abre menu interativo").set_defaults(func=do_menu)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args.func = do_menu
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n[riob-agent] cancelado pelo usuario", file=sys.stderr)
        return 130
    except AgentError as exc:
        print(f"[riob-agent] ERRO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
