"""Render a travel-plan HTML page from tripData JSON and assets/template.html.

退出码：0 成功 / 1 输入问题 / 2 模板问题。

校验口径：
- 阻断性错误（退出码非 0）：文件缺失、编码非 UTF-8、JSON 非法、顶层非对象、
  模板缺失或占位符与生成器映射不一致、输出不可写。
- 非阻断性告警（默认仍以退出码 0 产出）：字段类型异常、必填区块缺失或为空。
  这类数据模板会以空态降级渲染，不会中断整页；用 `--strict` 可把告警升级为阻断。
"""
from __future__ import annotations

import argparse
import codecs
import html
import json
import os
import re
import sys
import tempfile
import time

EXIT_OK = 0
EXIT_INPUT = 1
EXIT_TEMPLATE = 2

# Windows 下 os.replace 会因目标被瞬时占用报 WinError 5/32（PermissionError）。
# 实测 12 并发覆盖写 120 次命中 1 次，故做有界重试；耗尽仍原样抛出，不掩盖真实错误。
REPLACE_ATTEMPTS = 5
REPLACE_BACKOFF_SECONDS = 0.05

PLACEHOLDER_PATTERN = re.compile(r"\{\{([A-Z_]+)\}\}")
LEFTOVER_PATTERN = re.compile(r"\{\{[^{}]*\}\}")
NON_NUMERIC_PATTERN = re.compile(r"[^0-9.\-]")

# 占位符 -> tripData 字段。落进 HTML 文本/标题上下文，必须转义。
TEXT_PLACEHOLDERS = (
    ("TRIP_TITLE", "title", "标题"),
    ("DATE_RANGE", "dateRange", "日期范围"),
    ("TRAVELERS", "travelers", "出行人员"),
    ("GENERATION_DATE", "generationDate", "生成日期"),
)
BUDGET_CATEGORIES = ("transport", "accommodation", "food", "tickets", "other")
MAX_REPORTED_WARNINGS = 10


class InputError(Exception):
    """输入不满足生成前提。"""


def json_for_script(data):
    """序列化为可安全内联进 <script> 的 JSON 字面量。

    把 `<` `>` `&` 与 U+2028/U+2029 转成 \\uXXXX 转义：
    - `</` 不再出现，避免数据里的 `</script>` 提前闭合脚本块；
    - `<!--` 不再出现，避免 HTML 词法器进入 script data escaped 状态；
    - U+2028/U+2029 在旧引擎里是行终止符，会截断字符串字面量。

    这四个字符在 JSON 里只可能出现在字符串内部，替换不会破坏结构字符。
    """
    text = json.dumps(data, ensure_ascii=False, indent=2)
    for char, escape in (
        ("&", "\\u0026"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        text = text.replace(char, escape)
    return text


def text_value(value, label, warnings):
    """把标量字段收敛成字符串；非标量或布尔值降级为空串并记告警。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        warnings.append("%s 为布尔值，已按空值处理" % label)
        return ""
    if isinstance(value, (str, int, float)):
        return str(value)
    warnings.append(
        "%s 应为字符串，实际为 %s，已按空值处理" % (label, type(value).__name__)
    )
    return ""


def number_value(value, label, warnings, default=0):
    """把金额收敛成数字；支持千分位与货币符号前缀。"""
    if value is None:
        return default
    if isinstance(value, bool):
        warnings.append("%s 为布尔值，已按 %s 处理" % (label, default))
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            warnings.append("%s 为 NaN/Infinity，已按 %s 处理" % (label, default))
            return default
        return value
    if isinstance(value, str):
        cleaned = NON_NUMERIC_PATTERN.sub("", value)
        try:
            return int(cleaned) if cleaned and "." not in cleaned else float(cleaned)
        except ValueError:
            warnings.append(
                "%s 无法解析为数字（原值 %r），已按 %s 处理" % (label, value, default)
            )
            return default
    warnings.append(
        "%s 应为数字，实际为 %s，已按 %s 处理" % (label, type(value).__name__, default)
    )
    return default


def format_number(value):
    """整数型浮点去掉小数点，避免占位符里出现 8000.0。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def build_values(trip_data, warnings):
    values = {}
    for placeholder, field, label in TEXT_PLACEHOLDERS:
        # 文本上下文必须转义：标题里的 < & " 会破坏标签结构，</title> 可注入脚本。
        values[placeholder] = html.escape(text_value(trip_data.get(field), label, warnings))
    budget = trip_data.get("budget")
    if not isinstance(budget, dict):
        if budget is not None:
            warnings.append(
                "budget 应为对象，实际为 %s，预算数字按 0 显示" % type(budget).__name__
            )
        budget = {}
    values["TOTAL_BUDGET"] = format_number(
        number_value(budget.get("total"), "budget.total", warnings)
    )
    values["PER_PERSON"] = format_number(
        number_value(budget.get("perPerson"), "budget.perPerson", warnings)
    )
    # JSON 走独立转义通道，不参与 HTML 转义。
    values["TRIP_DATA_JSON"] = json_for_script(trip_data)
    return values


def collect_warnings(trip_data):
    """检查必填区块的完整度。返回告警列表，不抛异常。"""
    warnings = []
    for _, field, label in TEXT_PLACEHOLDERS:
        if trip_data.get(field) is None:
            warnings.append("%s（%s）缺失" % (label, field))
    collect_day_warnings(trip_data.get("days"), warnings)
    collect_hotel_warnings(trip_data.get("hotels"), warnings)
    collect_budget_warnings(trip_data.get("budget"), warnings)
    tips = trip_data.get("tips")
    if not isinstance(tips, list) or not tips:
        warnings.append("tips 缺失或为空数组，贴士区块将显示空态")
    return warnings


def collect_day_warnings(days, warnings):
    if not isinstance(days, list) or not days:
        warnings.append("days 缺失或为空数组，逐日天气与每日行程区块将显示空态")
        return
    for index, day in enumerate(days):
        if not isinstance(day, dict):
            warnings.append("days[%d] 应为对象，实际为 %s" % (index, type(day).__name__))
            continue
        for field in ("date", "weekday", "theme"):
            if not isinstance(day.get(field), str) or not day[field].strip():
                warnings.append("days[%d].%s 缺失" % (index, field))
        weather = day.get("weather")
        if not isinstance(weather, dict):
            warnings.append("days[%d].weather 缺失，该日图标与气温回落为默认值" % index)
        else:
            for field in ("icon", "high", "low"):
                if weather.get(field) is None:
                    warnings.append("days[%d].weather.%s 缺失" % (index, field))
        activities = day.get("activities")
        if not isinstance(activities, list) or not activities:
            warnings.append("days[%d].activities 缺失或为空数组" % index)
            continue
        for pos, activity in enumerate(activities):
            if not isinstance(activity, dict):
                warnings.append("days[%d].activities[%d] 应为对象" % (index, pos))
            elif not isinstance(activity.get("name"), str) or not activity["name"].strip():
                warnings.append("days[%d].activities[%d].name 缺失" % (index, pos))


def collect_hotel_warnings(hotels, warnings):
    if not isinstance(hotels, list) or not hotels:
        warnings.append("hotels 缺失或为空数组，住宿区块将显示空态")
        return
    for index, hotel in enumerate(hotels):
        if not isinstance(hotel, dict):
            warnings.append("hotels[%d] 应为对象，实际为 %s" % (index, type(hotel).__name__))
            continue
        if not isinstance(hotel.get("name"), str) or not hotel["name"].strip():
            warnings.append("hotels[%d].name 缺失" % index)
        # highlights 在模板里做字符串切分，非字符串会在渲染期抛错。
        if not isinstance(hotel.get("highlights"), str):
            warnings.append(
                "hotels[%d].highlights 应为分号或顿号分隔的字符串" % index
            )


def collect_budget_warnings(budget, warnings):
    if not isinstance(budget, dict):
        if budget is not None:
            warnings.append(
                "budget 应为对象，实际为 %s，预算区块将显示空态" % type(budget).__name__
            )
        else:
            warnings.append("budget 缺失，预算区块将显示空态")
        return
    for category in BUDGET_CATEGORIES:
        entry = budget.get(category)
        if entry is None:
            warnings.append("budget.%s 缺失" % category)
            continue
        if not isinstance(entry, dict):
            warnings.append("budget.%s 应为对象" % category)
            continue
        if entry.get("subtotal") is None:
            warnings.append("budget.%s.subtotal 缺失，按 0 计入占比" % category)
        items = entry.get("items")
        if not isinstance(items, list):
            warnings.append("budget.%s.items 应为数组" % category)
            continue
        for pos, item in enumerate(items):
            if not isinstance(item, dict):
                warnings.append("budget.%s.items[%d] 应为对象" % (category, pos))
                continue
            if not isinstance(item.get("name"), str) or not item["name"].strip():
                warnings.append("budget.%s.items[%d].name 缺失" % (category, pos))
            if item.get("cost") is None:
                warnings.append("budget.%s.items[%d].cost 缺失" % (category, pos))
    if budget.get("total") is None:
        warnings.append("budget.total 缺失，总预算按 0 显示")


def template_problems(template, values):
    """模板与生成器映射必须一一对应，两个方向都要检查。"""
    problems = []
    expected = {"{{%s}}" % key for key in values}
    unknown = sorted(
        {match.group(0) for match in LEFTOVER_PATTERN.finditer(template)} - expected
    )
    if unknown:
        problems.append("模板含生成器未处理的占位符：%s" % "、".join(unknown))
    unused = sorted(key for key in values if "{{%s}}" % key not in template)
    if unused:
        problems.append(
            "模板缺少这些占位符，产物会丢失对应数据：%s"
            % "、".join("{{%s}}" % key for key in unused)
        )
    return problems


def read_trip_data(data_path):
    """读取并解析 tripData；任何不满足前提的情况抛 InputError。"""
    if not os.path.isfile(data_path):
        raise InputError("tripData 文件不存在：%s" % data_path)
    try:
        with open(data_path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise InputError("tripData 读取失败：%s" % exc) from exc

    for bom, name in ((codecs.BOM_UTF16_LE, "UTF-16LE"), (codecs.BOM_UTF16_BE, "UTF-16BE")):
        if raw.startswith(bom):
            raise InputError("文件是 %s 编码，请另存为 UTF-8 后重试：%s" % (name, data_path))
    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[len(codecs.BOM_UTF8):]

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(
            "tripData 不是 UTF-8 编码（第 %d 字节起无法解码）：%s；请另存为 UTF-8 后重试"
            % (exc.start, data_path)
        ) from exc

    if not text.strip():
        raise InputError("tripData 是空文件：%s" % data_path)

    try:
        trip_data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise InputError("tripData 不是合法 JSON：%s" % exc) from exc
    except ValueError as exc:
        raise InputError("tripData 不是合法 JSON：%s" % exc) from exc

    if not isinstance(trip_data, dict):
        raise InputError(
            "tripData 顶层必须是 JSON 对象，实际为 %s" % type(trip_data).__name__
        )
    return trip_data


def _reject_constant(name):
    # Python 的 json 默认接受 NaN/Infinity，产出的 HTML 里会出现非标准 JSON。
    raise ValueError("含非标准常量 %s" % name)


def template_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, os.pardir, "assets", "template.html"))


def read_template():
    path = template_path()
    if not os.path.isfile(path):
        return None, "模板缺失：%s" % path
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read(), None
    except UnicodeDecodeError as exc:
        return None, "模板不是 UTF-8 编码：%s（%s）" % (path, exc)
    except OSError as exc:
        return None, "模板读取失败：%s" % exc


def same_path(left, right):
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def check_output_path(data_path, output_path):
    if os.path.isdir(output_path):
        raise InputError("输出路径是已存在的目录：%s" % output_path)
    if same_path(data_path, output_path):
        raise InputError("输出路径与输入路径相同，会覆盖源数据：%s" % output_path)
    parent = os.path.dirname(os.path.abspath(output_path))
    if not os.path.isdir(parent):
        raise InputError("输出目录不存在：%s" % parent)


def replace_with_retry(source, target):
    """把临时文件改名到目标位置；目标被短暂占用时有界重试。"""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_BACKOFF_SECONDS * (attempt + 1))


def atomic_write(path, text):
    """同目录临时文件 + 原子改名，避免写入中断留下半截产物。"""
    directory = os.path.dirname(os.path.abspath(path)) or os.curdir
    handle, temp_path = tempfile.mkstemp(prefix=".tripdata-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        replace_with_retry(temp_path, path)
    except BaseException:
        # 只删除本函数上一行刚创建的同目录临时文件；预检会把 os.unlink 记为
        # file_delete 能力，此处保留是为了不留下半截临时产物。
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def report_warnings(warnings, quiet):
    if not warnings or quiet:
        return
    print("结构告警（共 %d 条，产物已按空态降级生成）：" % len(warnings), file=sys.stderr)
    for item in warnings[:MAX_REPORTED_WARNINGS]:
        print("  - %s" % item, file=sys.stderr)
    if len(warnings) > MAX_REPORTED_WARNINGS:
        print("  - 其余 %d 条已省略" % (len(warnings) - MAX_REPORTED_WARNINGS), file=sys.stderr)


def generate(data_path, output_path, *, strict=False, quiet=False):
    try:
        trip_data = read_trip_data(data_path)
    except InputError as exc:
        print("输入错误：%s" % exc, file=sys.stderr)
        return EXIT_INPUT

    template, error = read_template()
    if template is None:
        print("模板错误：%s" % error, file=sys.stderr)
        return EXIT_TEMPLATE

    try:
        check_output_path(data_path, output_path)
    except InputError as exc:
        print("输入错误：%s" % exc, file=sys.stderr)
        return EXIT_INPUT

    warnings = collect_warnings(trip_data)
    values = build_values(trip_data, warnings)

    problems = template_problems(template, values)
    if problems:
        for item in problems:
            print("模板错误：%s" % item, file=sys.stderr)
        return EXIT_TEMPLATE

    report_warnings(warnings, quiet)
    if warnings and strict:
        print("严格模式：存在 %d 条结构告警，未生成产物" % len(warnings), file=sys.stderr)
        return EXIT_INPUT

    # 单遍替换：替换结果不再回扫，数据里出现的 {{...}} 字面量不会被二次替换。
    rendered = PLACEHOLDER_PATTERN.sub(lambda match: values[match.group(1)], template)

    try:
        atomic_write(output_path, rendered)
    except OSError as exc:
        print("输出写入失败：%s" % exc, file=sys.stderr)
        return EXIT_INPUT

    print("已生成：%s" % output_path)
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="按 assets/template.html 渲染行程 HTML 产物",
    )
    parser.add_argument("trip_data", help="tripData JSON 路径")
    parser.add_argument("output", help="输出 HTML 路径")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="存在结构告警时不产出，以退出码 1 退出",
    )
    parser.add_argument("--quiet", action="store_true", help="不打印结构告警")
    return parser


def main(argv):
    parser = build_parser()
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit as exc:
        # argparse 用法错误用 2，这里统一收敛到文档约定的退出码集合。
        return EXIT_OK if not exc.code else EXIT_INPUT
    return generate(args.trip_data, args.output, strict=args.strict, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
