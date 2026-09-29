"""Render a travel-plan HTML page from tripData JSON and assets/template.html."""
import json
import os
import re
import sys

PLACEHOLDER_PATTERN = re.compile(r"\{\{[A-Z_]+\}\}")
EXIT_OK = 0
EXIT_INPUT = 1
EXIT_TEMPLATE = 2


def json_for_script(data):
    """Serialize for embedding inside <script>; '</' must not close the block."""
    return json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")


def build_values(trip_data):
    budget = trip_data.get("budget")
    if not isinstance(budget, dict):
        budget = {}
    return {
        "{{TRIP_DATA_JSON}}": json_for_script(trip_data),
        "{{TRIP_TITLE}}": str(trip_data.get("title", "")),
        "{{DATE_RANGE}}": str(trip_data.get("dateRange", "")),
        "{{TRAVELERS}}": str(trip_data.get("travelers", "")),
        "{{TOTAL_BUDGET}}": str(budget.get("total", 0)),
        "{{PER_PERSON}}": str(budget.get("perPerson", 0)),
        "{{GENERATION_DATE}}": str(trip_data.get("generationDate", "")),
    }


def read_trip_data(data_path):
    if not os.path.isfile(data_path):
        print("tripData 文件不存在：%s" % data_path, file=sys.stderr)
        return None, EXIT_INPUT
    try:
        with open(data_path, "r", encoding="utf-8") as handle:
            trip_data = json.load(handle)
    except json.JSONDecodeError as exc:
        print("tripData 不是合法 JSON：%s" % exc, file=sys.stderr)
        return None, EXIT_INPUT
    except OSError as exc:
        print("tripData 读取失败：%s" % exc, file=sys.stderr)
        return None, EXIT_INPUT
    if not isinstance(trip_data, dict):
        print("tripData 顶层必须是 JSON 对象", file=sys.stderr)
        return None, EXIT_INPUT
    return trip_data, EXIT_OK


def template_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, os.pardir, "assets", "template.html")


def generate(data_path, output_path):
    trip_data, code = read_trip_data(data_path)
    if trip_data is None:
        return code

    path = template_path()
    if not os.path.isfile(path):
        print("模板缺失：%s" % path, file=sys.stderr)
        return EXIT_TEMPLATE
    with open(path, "r", encoding="utf-8") as handle:
        template = handle.read()

    values = build_values(trip_data)
    unknown = sorted(set(PLACEHOLDER_PATTERN.findall(template)) - set(values))
    if unknown:
        print("模板含脚本未处理的占位符：%s" % ", ".join(unknown), file=sys.stderr)
        return EXIT_TEMPLATE

    html = template
    for placeholder, value in values.items():
        html = html.replace(placeholder, value)

    try:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(html)
    except OSError as exc:
        print("输出写入失败：%s" % exc, file=sys.stderr)
        return EXIT_INPUT

    print("已生成：%s" % output_path)
    return EXIT_OK


def main(argv):
    if len(argv) != 3:
        print("用法：python %s <tripData.json> <输出.html>" % argv[0], file=sys.stderr)
        return EXIT_INPUT
    return generate(argv[1], argv[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
