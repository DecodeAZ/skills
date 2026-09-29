"""Read-only environment readiness check for the travel-planner skill.

Checks presence of the declared dependencies and reports one of:
ready / partial / needs_setup / unavailable. It never installs, logs in,
authenticates, reads credentials or modifies configuration.
"""
import json
import os
import shutil
import sys
from datetime import datetime

REQUIRED_PYTHON = (3, 9)
NODE_MIN_MAJOR = 18
MC_PORTER_NODE_MAJOR = 20

SETUP_GUIDE = "references/setup-guide.md"


def find_executable(name):
    return shutil.which(name)


def package_files():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_dir = os.path.abspath(os.path.join(script_dir, os.pardir))
    return {
        "generator": os.path.join(script_dir, "generate.py"),
        "template": os.path.join(skill_dir, "assets", "template.html"),
    }


def run_check():
    checks = []

    py_ok = sys.version_info[:2] >= REQUIRED_PYTHON
    checks.append({
        "name": "Python",
        "kind": "required",
        "available": py_ok,
        "detail": "当前 %d.%d，需 >= %d.%d" % (
            sys.version_info[0], sys.version_info[1],
            REQUIRED_PYTHON[0], REQUIRED_PYTHON[1]),
    })

    node_path = find_executable("node")
    checks.append({
        "name": "Node.js",
        "kind": "required",
        "available": bool(node_path),
        "detail": "检测到 %s，需 >= %d；flyai 与 mcporter 的前置" % (
            node_path, NODE_MIN_MAJOR) if node_path else
            "未检测到 node，需 >= %d（flyai 与 mcporter 的前置）" % NODE_MIN_MAJOR,
    })

    flyai_path = find_executable("flyai")
    checks.append({
        "name": "FlyAI CLI (flyai)",
        "kind": "required",
        "available": bool(flyai_path),
        "detail": "检测到 %s" % flyai_path if flyai_path else
            "未检测到，机票/酒店/门票只能给出参考价，预算中不再有\"实查\"等级",
    })

    mcporter_path = find_executable("mcporter")
    checks.append({
        "name": "mcporter",
        "kind": "optional",
        "available": bool(mcporter_path),
        "detail": "检测到 %s，需 >= Node %d；小红书通道还需另配 MCP 服务" % (
            mcporter_path, MC_PORTER_NODE_MAJOR) if mcporter_path else
            "未检测到，将失去小红书真实住客反馈；改用通用网络搜索替代",
    })

    files = package_files()
    missing_files = [k for k, v in files.items() if not os.path.isfile(v)]
    checks.append({
        "name": "包内生成器与模板",
        "kind": "required",
        "available": not missing_files,
        "detail": "完整" if not missing_files else
            "缺失：%s" % ", ".join(missing_files),
    })

    by_name = {c["name"]: c for c in checks}
    missing_required = [c["name"] for c in checks
                        if c["kind"] == "required" and not c["available"]]
    missing_optional = [c["name"] for c in checks
                        if c["kind"] == "optional" and not c["available"]]

    next_steps = []
    if missing_files:
        status = "unavailable"
        next_steps.append("包体不完整，技能无法产出 HTML。请重新安装本技能。")
    elif not by_name["Node.js"]["available"]:
        status = "needs_setup"
        next_steps.append("先安装 Node.js >= 18：https://nodejs.org/")
        next_steps.append("详见 %s" % SETUP_GUIDE)
    elif not by_name["FlyAI CLI (flyai)"]["available"]:
        status = "needs_setup"
        next_steps.append("安装 FlyAI CLI：npm i -g @fly-ai/flyai-cli")
        next_steps.append("验证：flyai keyword-search --query \"杭州\"")
        next_steps.append("详见 %s" % SETUP_GUIDE)
    elif not by_name["mcporter"]["available"]:
        status = "partial"
        next_steps.append("可选：npm i -g mcporter（需 Node >= 20），并配置小红书 MCP 服务")
    else:
        status = "ready"

    return {
        "status": status,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "platform": sys.platform,
        "checks": checks,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "next_steps": next_steps,
        "degradation": {
            "needs_setup": "仅用通用网络搜索采集数据；预算不再标注\"实查\"，机票酒店全部为参考价或估算，交付时必须声明。",
            "partial": "FlyAI 实时报价可用；小红书通道缺失，真实住客反馈以通用搜索替代，需声明来源降级。",
            "unavailable": "停止生成行程。不得凭记忆编造价格或班次。",
        }.get(status, ""),
    }


if __name__ == "__main__":
    print(json.dumps(run_check(), ensure_ascii=False, indent=2))
    sys.exit(0)
