#!/usr/bin/env python3
"""travel-planner 技能自测：不联网、不启动子进程。

覆盖三块：
1. scripts/generate.py —— 输入校验、HTML 转义、单遍替换、原子写与退出码契约；
2. scripts/collect_self_probe.py —— 探测判定口径（含误判回归）与结果结构约束；
3. skill-dependencies.json —— 与 setup-guide、采集器之间的静态一致性。

用法：
    python -B scripts/selftest.py
退出码：0 全部通过 / 1 存在失败。

注意：脚本会在导入前关闭字节码写入，避免在 scripts/ 下留下 __pycache__
而被预检扫描判为无法静态分析的文件。
"""
import sys

sys.dont_write_bytecode = True

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
EXAMPLE_SOURCE = SKILL_ROOT / "assets" / "examples" / "sources" / "tripData-成都.json"
SETUP_GUIDE = SKILL_ROOT / "references" / "setup-guide.md"
MANIFEST = SKILL_ROOT / "skill-dependencies.json"

CHECK_TYPES = {"auth_probe", "mcp_probe", "cli_probe"}
STATUSES = {"ready", "missing", "unavailable"}
REASON_CODES = {
    "ok",
    "auth_expired_or_invalid",
    "permission_denied",
    "quota_or_rate_limit",
    "service_error",
    "network_or_timeout",
    "version_incompatible",
    "configuration_invalid",
    "mcp_not_registered",
    "probe_failed",
}
RESULT_FIELDS = {"check_type", "target", "status", "reason_code", "checked_at"}
CHECKED_AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SECRET_PATTERN = re.compile(r"AKIA[0-9A-Z]{16}|sk_[A-Za-z0-9_-]{16,}")

CHECKS = 0
FAILURES = []


def check(name, condition, detail=""):
    global CHECKS
    CHECKS += 1
    if condition:
        print("  ok    " + name)
        return True
    FAILURES.append(name)
    print("  FAIL  " + name + ("  -> %r" % (detail,) if detail != "" else ""))
    return False


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, str(SCRIPTS_DIR / filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


generate = load_module("travel_planner_generate", "generate.py")
probe = load_module("travel_planner_probe", "collect_self_probe.py")

SAMPLE_TRIP = json.loads(EXAMPLE_SOURCE.read_text(encoding="utf-8"))


def write_json(path, payload, encoding="utf-8"):
    text = json.dumps(payload, ensure_ascii=False)
    if encoding == "utf-8":
        path.write_text(text, encoding="utf-8")
    else:
        path.write_bytes(text.encode(encoding))
    return path


def leftover_temp_files(directory):
    return sorted(p.name for p in Path(directory).iterdir() if p.name.startswith(".tripdata-"))


def test_generate_escaping():
    print("\n[generate] 内联 JSON 转义")
    source = {
        "title": "含 </script> 与 <!-- 注释",
        "tips": ["a<b>c&d", "行分隔\u2028结束"],
        "count": 1,
    }
    literal = generate.json_for_script(source)
    check("不含裸 </", "</" not in literal)
    check("不含裸 <", "<" not in literal)
    check("不含 HTML 注释起点", "<!--" not in literal)
    check("不含 U+2028", "\u2028" not in literal)
    check("不含裸 &", "&" not in literal)
    check("往返语义不变", json.loads(literal) == source, literal[:60])


def test_generate_coercion():
    print("\n[generate] 字段类型收敛")
    check("字符串原样返回", generate.text_value("甲", "标题", []) == "甲")
    check("数字转字符串", generate.text_value(12, "标题", []) == "12")
    check("布尔降级为空并告警", generate.text_value(True, "标题", []) == "" and len([]) == 0)
    warnings = []
    check("布尔会写告警", generate.text_value(True, "标题", warnings) == "" and warnings)
    check("列表降级为空", generate.text_value(["x"], "标题", []) == "")
    check("对象降级为空", generate.text_value({"a": 1}, "标题", []) == "")
    check("None 降级为空", generate.text_value(None, "标题", []) == "")

    check("整数金额", generate.number_value(8000, "m", []) == 8000)
    check("千分位金额", generate.number_value("¥8,000", "m", []) == 8000)
    check("小数金额", generate.number_value("80.5", "m", []) == 80.5)
    check("非法文案归零", generate.number_value("很多", "m", []) == 0)
    check("NaN 归零", generate.number_value(float("nan"), "m", []) == 0)
    check("Infinity 归零", generate.number_value(float("inf"), "m", []) == 0)
    check("布尔金额归零", generate.number_value(True, "m", []) == 0)
    check("整数型浮点去尾", generate.format_number(8000.0) == "8000")
    check("小数保留", generate.format_number(80.5) == "80.5")


def test_generate_values():
    print("\n[generate] 占位符取值与转义")
    warnings = []
    values = generate.build_values(
        {"title": '"></title><script>x</script>', "budget": {"total": 100}}, warnings
    )
    check("标题已 HTML 转义", "<" not in values["TRIP_TITLE"] and "&lt;" in values["TRIP_TITLE"])
    check("金额已格式化", values["TOTAL_BUDGET"] == "100")
    check("缺字段取空串", values["DATE_RANGE"] == "" and values["GENERATION_DATE"] == "")
    check("内联 JSON 不做 HTML 转义", "&lt;" not in values["TRIP_DATA_JSON"])
    check("内联 JSON 保持可解析", json.loads(values["TRIP_DATA_JSON"])["title"].startswith('">'))


def test_generate_warnings():
    print("\n[generate] 结构告警")
    warnings = generate.collect_warnings({"title": "只有标题"})
    for keyword in ("days", "hotels", "budget", "tips"):
        check("缺失 %s 有告警" % keyword, any(keyword in item for item in warnings))
    check("完整样例零告警", generate.collect_warnings(SAMPLE_TRIP) == [],
          generate.collect_warnings(SAMPLE_TRIP)[:3])

    broken = json.loads(json.dumps(SAMPLE_TRIP))
    broken["hotels"] = [{"name": "缺 highlights"}]
    check("highlights 类型告警",
          any("highlights" in item for item in generate.collect_warnings(broken)))
    broken = json.loads(json.dumps(SAMPLE_TRIP))
    broken["budget"]["transport"].pop("subtotal")
    check("subtotal 缺失告警",
          any("subtotal" in item for item in generate.collect_warnings(broken)))
    broken = json.loads(json.dumps(SAMPLE_TRIP))
    broken["days"][0]["weather"].pop("icon")
    check("weather.icon 缺失告警",
          any("weather.icon" in item for item in generate.collect_warnings(broken)))


def test_template_mapping():
    print("\n[generate] 模板与映射一致性")
    template, error = generate.read_template()
    check("模板可读", template is not None, error)
    values = generate.build_values({}, [])
    check("当前模板映射一致", generate.template_problems(template, values) == [],
          generate.template_problems(template, values))
    check("模板缺占位符被判错", generate.template_problems("{{TRIP_TITLE}}", values) != [])
    check("模板多占位符被判错",
          generate.template_problems(template + "{{NOT_MAPPED}}", values) != [])
    check("畸形占位符被判错",
          generate.template_problems(template + "{{ trip title }}", values) != [])


def test_generate_exit_codes():
    print("\n[generate] 退出码契约与边界输入")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        ok_src = write_json(root / "ok.json", SAMPLE_TRIP)
        out = root / "ok.html"

        check("正常输入返回 0", quiet(generate.generate, str(ok_src), str(out)) == 0)
        check("产物已落盘", out.is_file() and out.stat().st_size > 0)
        first = out.read_bytes()
        check("重复调用返回 0", quiet(generate.generate, str(ok_src), str(out)) == 0)
        check("重复调用产物一致", out.read_bytes() == first)
        check("无临时文件残留", leftover_temp_files(root) == [], leftover_temp_files(root))

        check("文件不存在返回 1",
              quiet(generate.generate, str(root / "none.json"), str(root / "a.html")) == 1)

        gb = root / "gb18030.json"
        write_json(gb, SAMPLE_TRIP, encoding="gb18030")
        check("非 UTF-8 返回 1 且不崩溃", quiet(generate.generate, str(gb), str(out)) == 1)

        utf16 = root / "utf16.json"
        utf16.write_bytes(json.dumps(SAMPLE_TRIP, ensure_ascii=False).encode("utf-16"))
        check("UTF-16 返回 1", quiet(generate.generate, str(utf16), str(out)) == 1)

        bom = root / "bom.json"
        bom.write_bytes(b"\xef\xbb\xbf" + json.dumps(SAMPLE_TRIP).encode("utf-8"))
        check("带 BOM 的 UTF-8 可接受",
              quiet(generate.generate, str(bom), str(root / "bom.html")) == 0)

        blank = root / "blank.json"
        blank.write_text("   \n", encoding="utf-8")
        check("空白文件返回 1", quiet(generate.generate, str(blank), str(out)) == 1)

        array_top = root / "array.json"
        array_top.write_text("[1, 2, 3]", encoding="utf-8")
        check("顶层数组返回 1", quiet(generate.generate, str(array_top), str(out)) == 1)

        truncated = root / "truncated.json"
        truncated.write_text(json.dumps(SAMPLE_TRIP)[:200], encoding="utf-8")
        check("截断 JSON 返回 1", quiet(generate.generate, str(truncated), str(out)) == 1)

        nan_src = root / "nan.json"
        nan_src.write_text('{"title":"x","budget":{"total":NaN}}', encoding="utf-8")
        check("NaN 常量返回 1", quiet(generate.generate, str(nan_src), str(out)) == 1)

        check("输出目录不存在返回 1",
              quiet(generate.generate, str(ok_src), str(root / "missing" / "x.html")) == 1)
        check("输出与输入同路径返回 1",
              quiet(generate.generate, str(ok_src), str(ok_src)) == 1)
        check("输出是目录返回 1", quiet(generate.generate, str(ok_src), str(root)) == 1)

        partial = root / "partial.json"
        write_json(partial, {"title": "只有标题"})
        partial_out = root / "partial.html"
        check("有结构告警仍返回 0",
              quiet(generate.generate, str(partial), str(partial_out)) == 0)
        check("告警产物已落盘", partial_out.is_file())

        strict_out = root / "strict.html"
        check("严格模式返回 1",
              quiet(generate.generate, str(partial), str(strict_out), strict=True) == 1)
        check("严格模式不落盘", not strict_out.exists())

        check("用法错误返回 1", quiet(generate.main, ["generate.py"]) == 1)
        check("--help 返回 0", quiet(generate.main, ["generate.py", "--help"]) == 0)


def test_single_pass_substitution():
    print("\n[generate] 单遍替换")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        payload = json.loads(json.dumps(SAMPLE_TRIP))
        payload["tips"] = ["字面量 {{TOTAL_BUDGET}} 与 {{TRIP_TITLE}} 必须原样保留"]
        src = write_json(root / "tricky.json", payload)
        out = root / "tricky.html"
        check("渲染返回 0", quiet(generate.generate, str(src), str(out)) == 0)
        html = out.read_text(encoding="utf-8")
        check("数据内占位符未被二次替换",
              "{{TOTAL_BUDGET}}" in html and "{{TRIP_TITLE}}" in html)
        check("模板占位符已被替换", "{{TOTAL_BUDGET}}" not in html.split("const tripData")[0])


def test_atomic_write_failure():
    print("\n[generate] 写入失败时的清理")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        src = write_json(root / "ok.json", SAMPLE_TRIP)
        out = root / "out.html"
        original = generate.os.replace

        def boom(*args, **kwargs):
            raise OSError("模拟替换失败")

        generate.os.replace = boom
        try:
            code = quiet(generate.generate, str(src), str(out))
        finally:
            generate.os.replace = original
        check("替换失败返回 1", code == 1, code)
        check("失败后不留下临时文件", leftover_temp_files(root) == [], leftover_temp_files(root))
        check("失败后不产出半截文件", not out.exists())


def test_replace_retry():
    print("\n[generate] 目标被瞬时占用时的有界重试")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        src = write_json(root / "ok.json", SAMPLE_TRIP)
        out = root / "retry.html"
        original = generate.os.replace
        state = {"calls": 0}

        def flaky(source, target):
            state["calls"] += 1
            if state["calls"] < 3:
                raise PermissionError(13, "目标被占用")
            return original(source, target)

        generate.os.replace = flaky
        try:
            code = quiet(generate.generate, str(src), str(out))
        finally:
            generate.os.replace = original
        check("瞬时占用重试后成功", code == 0, code)
        check("确实发生了重试", state["calls"] == 3, state["calls"])
        check("重试成功后产物存在", out.is_file())
        check("重试后无临时文件残留", leftover_temp_files(root) == [], leftover_temp_files(root))

        state["calls"] = 0

        def always(source, target):
            state["calls"] += 1
            raise PermissionError(13, "目标持续被占用")

        out2 = root / "retry-fail.html"
        generate.os.replace = always
        try:
            code = quiet(generate.generate, str(src), str(out2))
        finally:
            generate.os.replace = original
        check("持续占用最终返回 1", code == 1, code)
        check("重试次数有上限", state["calls"] == generate.REPLACE_ATTEMPTS, state["calls"])
        check("耗尽重试后不留下临时文件", leftover_temp_files(root) == [], leftover_temp_files(root))

        def unexpected(source, target):
            raise OSError("非占用类错误")

        generate.os.replace = unexpected
        try:
            code = quiet(generate.generate, str(src), str(root / "other.html"))
        finally:
            generate.os.replace = original
        check("非占用类错误不重试", code == 1, code)


def test_cli_envelope():
    print("\n[probe] flyai 判定口径（退出码不可信）")
    ready = probe.classify_cli_envelope(
        0, '{"status":0,"data":{"itemList":[{"a":1}]},"message":"success"}', "")
    check("正常信封判为可用", ready == (probe.STATUS_READY, probe.REASON_OK), ready)

    business_fail = probe.classify_cli_envelope(
        0, '{"data":null,"message":"出发日期非法","status":1}', "")
    check("退出码 0 但业务失败判为不可用",
          business_fail[0] == probe.STATUS_UNAVAILABLE, business_fail)
    check("参数类失败归为配置原因", business_fail[1] == probe.REASON_CONFIG, business_fail)

    empty = probe.classify_cli_envelope(0, '{"data":null,"message":"empty","status":0}', "")
    check("查询成功但无数据判为不可用",
          empty == (probe.STATUS_UNAVAILABLE, probe.REASON_SERVICE), empty)

    quota = probe.classify_cli_envelope(
        0, '{"status":1,"message":"请求过于频繁 rate limit exceeded","data":null}', "")
    check("限流文案归为配额原因", quota[1] == probe.REASON_QUOTA, quota)

    timeout = probe.classify_cli_envelope(124, "", "timeout")
    check("超时归为网络原因",
          timeout == (probe.STATUS_UNAVAILABLE, probe.REASON_NETWORK), timeout)

    unknown = probe.classify_cli_envelope(1, "", "error: unknown command 'x'")
    check("未知子命令归为配置原因", unknown[1] == probe.REASON_CONFIG, unknown)

    non_json = probe.classify_cli_envelope(0, "Usage: flyai [options] [command]", "")
    check("非 JSON 输出判为不可用", non_json[0] == probe.STATUS_UNAVAILABLE, non_json)

    payload_hit = probe.classify_cli_envelope(
        0, '{"status":0,"data":{"itemList":[{"price":"403","name":"403 路公交"}]}}', "")
    check("载荷里的 403 不误判为限流",
          payload_hit == (probe.STATUS_READY, probe.REASON_OK), payload_hit)

    stderr_hit = probe.classify_cli_envelope(1, "", "HTTP 403 Forbidden")
    check("stderr 里的 403 才归为配额原因", stderr_hit[1] == probe.REASON_QUOTA, stderr_hit)


def test_api_classification():
    print("\n[probe] API Key 判定口径")
    check("高德成功信封", probe.is_success_payload({"status": "1", "info": "OK"}) is True)
    check("和风成功信封", probe.is_success_payload({"code": "200"}) is True)
    check("失败信封不通过",
          probe.is_success_payload({"status": "0", "info": "INVALID_USER_KEY"}) is False)
    check("INVALID_USER_KEY 归为鉴权",
          probe.classify_api_failure({"status": "0", "info": "INVALID_USER_KEY"})
          == probe.REASON_AUTH)
    check("和风 403 归为鉴权", probe.classify_api_failure({"code": "403"}) == probe.REASON_AUTH)
    check("和风 402 归为配额", probe.classify_api_failure({"code": "402"}) == probe.REASON_QUOTA)
    check("未知 failures 归为探测失败",
          probe.classify_api_failure({"code": "999"}) == probe.REASON_PROBE_FAILED)


def test_safe_probe_pairing():
    print("\n[probe] 结果与 schema 的配对约束")
    forced = probe.safe_probe("cli_probe", "t", lambda: (probe.STATUS_READY, probe.REASON_SERVICE))
    check("ready 强制配 ok", forced["reason_code"] == probe.REASON_OK, forced)
    flipped = probe.safe_probe("cli_probe", "t", lambda: (probe.STATUS_MISSING, probe.REASON_OK))
    check("非 ready 不得配 ok", flipped["reason_code"] != probe.REASON_OK, flipped)

    def boom():
        raise RuntimeError("模拟探测内部异常")

    crashed = probe.safe_probe("cli_probe", "t", boom)
    check("探测抛错被收敛为不可用",
          crashed["status"] == probe.STATUS_UNAVAILABLE
          and crashed["reason_code"] == probe.REASON_PROBE_FAILED, crashed)

    empty_env = probe.probe_api_key("TRAVEL_PLANNER_ABSENT_KEY_ENV", "https://example.invalid/x?key=")
    check("未配置 Key 判为缺失且不发起请求",
          empty_env == (probe.STATUS_MISSING, probe.REASON_CONFIG), empty_env)


def collect_with_stubs(status=None):
    status = status or (probe.STATUS_MISSING, probe.REASON_PROBE_FAILED)
    names = ("probe_flyai", "probe_mcporter", "probe_qweather", "probe_amap")
    original = {name: getattr(probe, name) for name in names}
    for name in names:
        setattr(probe, name, lambda: status)
    try:
        return probe.collect()
    finally:
        for name, func in original.items():
            setattr(probe, name, func)


def validate_probe_results(results):
    """本地复刻 probe-results schema 的必填、枚举与联合约束。"""
    problems = []
    if not isinstance(results, dict) or not results:
        return ["结果必须是非空对象"]
    for dependency_id, checks in results.items():
        if not isinstance(checks, dict) or not checks:
            problems.append("%s 的检查集合为空" % dependency_id)
            continue
        for check_id, item in checks.items():
            label = "%s.%s" % (dependency_id, check_id)
            if not isinstance(item, dict):
                problems.append(label + " 不是对象")
                continue
            missing = RESULT_FIELDS - set(item)
            if missing:
                problems.append(label + " 缺字段 " + ",".join(sorted(missing)))
            extra = set(item) - RESULT_FIELDS
            if extra:
                problems.append(label + " 含未知字段 " + ",".join(sorted(extra)))
            if item.get("check_type") not in CHECK_TYPES:
                problems.append(label + " check_type 非法")
            if item.get("status") not in STATUSES:
                problems.append(label + " status 非法")
            if item.get("reason_code") not in REASON_CODES:
                problems.append(label + " reason_code 非法")
            if not isinstance(item.get("target"), str) or not item.get("target"):
                problems.append(label + " target 必须是非空字符串")
            if not CHECKED_AT_PATTERN.match(str(item.get("checked_at", ""))):
                problems.append(label + " checked_at 格式不符")
            if item.get("status") == "ready" and item.get("reason_code") != "ok":
                problems.append(label + " ready 必须配 ok")
            if item.get("status") in {"missing", "unavailable"} and item.get("reason_code") == "ok":
                problems.append(label + " 非 ready 不得配 ok")
    return problems


def test_result_schema():
    print("\n[probe] 结果文件结构")
    healthy = probe.safe_probe("cli_probe", "flyai keyword-search", lambda: (probe.STATUS_READY, probe.REASON_OK))
    broken_pair = dict(healthy, status="ready", reason_code="service_error")
    sample = {"demo": {"demo-check": healthy}}
    check("合规结果通过校验", validate_probe_results(sample) == [],
          validate_probe_results(sample))
    check("校验器能发现配对违规",
          validate_probe_results({"demo": {"demo-check": broken_pair}}) != [])
    check("校验器能发现缺字段",
          validate_probe_results({"demo": {"demo-check": {"status": "ready"}}}) != [])
    check("校验器能发现枚举外取值",
          validate_probe_results({"demo": {"demo-check": dict(healthy, status="degraded")}}) != [])
    check("校验器能发现时间格式错误",
          validate_probe_results({"demo": {"demo-check": dict(healthy, checked_at="2026-10-05")}}) != [])

    results = collect_with_stubs()
    check("采集器结果满足 schema", validate_probe_results(results) == [],
          validate_probe_results(results))

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    declared = {
        (dependency["id"], check_item["id"])
        for dependency in manifest.get("dependencies", [])
        for check_item in dependency.get("checks", [])
        if check_item.get("type") in {"cli_probe", "auth_probe"}
    }
    collected = {
        (dependency_id, check_id)
        for dependency_id, checks in results.items()
        for check_id in checks
    }
    check("采集器覆盖清单中全部 cli_probe/auth_probe 检查",
          declared == collected, sorted(declared ^ collected))


def test_write_results():
    print("\n[probe] 结果落盘")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        target = root / "nested" / "probe-results.json"
        payload = {"flyai-cli": {"flyai-probe": probe.safe_probe(
            "cli_probe", "flyai keyword-search", lambda: (probe.STATUS_READY, probe.REASON_OK))}}
        probe.write_results(target, payload)
        check("自动创建父目录", target.is_file())
        check("内容可解析", json.loads(target.read_text(encoding="utf-8"))["flyai-cli"]["flyai-probe"]["status"] == "ready")
        check("覆盖写幂等",
              probe.write_results(target, payload) is None and target.is_file())
        check("无临时文件残留",
              [p.name for p in target.parent.iterdir() if p.name.startswith(".probe-results-")] == [])
        check("包内路径可识别", probe.inside_skill_package(SKILL_ROOT / "x.json") is True)
        check("包外路径可识别", probe.inside_skill_package(root / "x.json") is False)


def test_manifest():
    print("\n[清单] skill-dependencies.json 静态一致性")
    raw = MANIFEST.read_text(encoding="utf-8")
    data = json.loads(raw)
    check("schema_version 为字符串 1", data.get("schema_version") == "1")

    capabilities = data.get("capabilities") or []
    covered = [item.get("capability") for item in data.get("functional_degradations") or []]
    check("能力与普通功能降级一一对应", sorted(capabilities) == sorted(covered),
          sorted(set(capabilities) ^ set(covered)))

    dependencies = data.get("dependencies") or []
    ids = [dependency.get("id") for dependency in dependencies]
    check("依赖 id 唯一", len(ids) == len(set(ids)), ids)

    status_problems = []
    for dependency in dependencies:
        for check_item in dependency.get("checks", []):
            if check_item.get("type") == "url":
                value = check_item.get("expected_status")
                if not isinstance(value, list) or not value or not all(
                    isinstance(item, int) for item in value
                ):
                    status_problems.append(
                        "%s.%s 应为整数数组" % (dependency["id"], check_item["id"])
                    )
    check("url 检查的 expected_status 均为整数数组", status_problems == [], status_problems)

    check_allowed = {
        "id", "type", "required", "target", "command", "min_version", "name",
        "path", "field", "server", "url", "method", "expected_status",
    }
    unknown_fields = []
    for dependency in dependencies:
        for check_item in dependency.get("checks", []):
            extra = set(check_item) - check_allowed
            if extra:
                unknown_fields.append("%s.%s -> %s" % (
                    dependency["id"], check_item["id"], sorted(extra)))
    check("检查项无未知字段", unknown_fields == [], unknown_fields)

    setup_guide = SETUP_GUIDE.read_text(encoding="utf-8")
    missing_ids = [dependency_id for dependency_id in ids if dependency_id not in setup_guide]
    check("每个依赖 id 都出现在 setup-guide", missing_ids == [], missing_ids)

    urls = set()
    for dependency in dependencies:
        setup = dependency.get("setup") or {}
        for value in setup.values():
            if isinstance(value, str) and value.startswith("https://"):
                urls.add(value)
    missing_urls = sorted(url for url in urls if url not in setup_guide)
    check("setup 中的 https 入口都出现在 setup-guide", missing_urls == [], missing_urls)

    check("清单内无明文凭据", SECRET_PATTERN.search(raw) is None)


def main():
    print("travel-planner 自测开始（不联网、不启动子进程）")
    test_generate_escaping()
    test_generate_coercion()
    test_generate_values()
    test_generate_warnings()
    test_template_mapping()
    test_generate_exit_codes()
    test_single_pass_substitution()
    test_atomic_write_failure()
    test_replace_retry()
    test_cli_envelope()
    test_api_classification()
    test_safe_probe_pairing()
    test_result_schema()
    test_write_results()
    test_manifest()

    print("\n断言 %d 项，失败 %d 项" % (CHECKS, len(FAILURES)))
    if FAILURES:
        print("失败项：")
        for name in FAILURES:
            print("  - " + name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
