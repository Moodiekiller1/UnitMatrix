import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from flask import Flask, render_template, request, session


app = Flask(__name__)
app.secret_key = os.environ.get(
    "UNITMATRIX_SECRET_KEY",
    "dev-only-change-this-secret-key-before-production",
)

CATEGORY_OPTIONS = {
    "length": {
        "label": "Length",
        "default_from": "km",
        "default_to": "m",
        "units": {
            "km": "Kilometers",
            "m": "Meters",
            "cm": "Centimeters",
            "mm": "Millimeters",
        },
    },
    "weight": {
        "label": "Weight",
        "default_from": "t",
        "default_to": "kg",
        "units": {
            "t": "Tonnes",
            "kg": "Kilograms",
            "g": "Grams",
            "mg": "Milligrams",
        },
    },
    "temp": {
        "label": "Temperature",
        "default_from": "c",
        "default_to": "f",
        "units": {
            "c": "Celsius",
            "f": "Fahrenheit",
            "k": "Kelvin",
        },
    },
    "num": {
        "label": "Number Systems",
        "default_from": "dec",
        "default_to": "bin",
        "units": {
            "dec": "Decimal",
            "bin": "Binary",
            "hex": "Hexadecimal",
        },
    },
}

UNIT_NAMES = {
    unit: label
    for category in CATEGORY_OPTIONS.values()
    for unit, label in category["units"].items()
}

LENGTH_FACTORS = {
    "km": Decimal("1000"),
    "m": Decimal("1"),
    "cm": Decimal("0.01"),
    "mm": Decimal("0.001"),
}

WEIGHT_FACTORS = {
    "t": Decimal("1000"),
    "kg": Decimal("1"),
    "g": Decimal("0.001"),
    "mg": Decimal("0.000001"),
}

NUMERIC_INPUT_PATTERN = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$")
SCIENTIFIC_INPUT_PATTERN = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d+$")
MAX_INPUT_CHARS = 80
MAX_DECIMAL_DIGITS = 18
MAX_NUMBER_SYSTEM_CHARS = 256
MAX_HISTORY_ITEMS = 30
MAIN_HISTORY_ITEMS = 10
MAX_RESULT_CHARS = 600


def clamp_precision(value):
    try:
        precision = int(value)
    except (TypeError, ValueError):
        return 4
    return min(max(precision, 0), 8)


def normalize_history():
    history = session.get("history", [])
    if not isinstance(history, list):
        history = []

    cleaned = []
    for item in history:
        if not isinstance(item, dict):
            continue
        required = {"label", "input_val", "output_val", "from_label", "to_label", "category"}
        if required.issubset(item):
            cleaned.append(item)

    session["history"] = cleaned[:MAX_HISTORY_ITEMS]
    session.modified = True


def get_default_state():
    category = "length"
    return {
        "category": category,
        "from_unit": CATEGORY_OPTIONS[category]["default_from"],
        "to_unit": CATEGORY_OPTIONS[category]["default_to"],
        "raw_val": "",
        "precision": clamp_precision(session.get("precision", 4)),
    }


def sanitize_state(form):
    state = get_default_state()

    category = (form.get("category") or state["category"]).strip().lower()
    if category not in CATEGORY_OPTIONS:
        category = state["category"]

    valid_units = CATEGORY_OPTIONS[category]["units"]
    from_unit = (form.get("from_unit") or CATEGORY_OPTIONS[category]["default_from"]).strip().lower()
    to_unit = (form.get("to_unit") or CATEGORY_OPTIONS[category]["default_to"]).strip().lower()

    if from_unit not in valid_units:
        from_unit = CATEGORY_OPTIONS[category]["default_from"]
    if to_unit not in valid_units:
        to_unit = CATEGORY_OPTIONS[category]["default_to"]

    raw_val = (form.get("value") or "").strip()
    if len(raw_val) > MAX_INPUT_CHARS and category != "num":
        raw_val = raw_val[:MAX_INPUT_CHARS]
    if len(raw_val) > MAX_NUMBER_SYSTEM_CHARS and category == "num":
        raw_val = raw_val[:MAX_NUMBER_SYSTEM_CHARS]

    precision = clamp_precision(form.get("precision", session.get("precision", 4)))
    session["precision"] = precision

    return {
        "category": category,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "raw_val": raw_val,
        "precision": precision,
    }


def validate_decimal_input(raw_value, allow_negative=False):
    if not raw_value:
        return None, "Error: Please enter a value."
    if SCIENTIFIC_INPUT_PATTERN.fullmatch(raw_value):
        return None, "Error: Scientific notation is not supported."
    if len(raw_value) > MAX_INPUT_CHARS:
        return None, "Error: Value is too large."
    if not NUMERIC_INPUT_PATTERN.fullmatch(raw_value):
        return None, "Error: Input must be a valid number."

    digit_count = sum(char.isdigit() for char in raw_value)
    if digit_count > MAX_DECIMAL_DIGITS:
        return None, "Error: Value is too large."

    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        return None, "Error: Input must be a valid number."

    if not allow_negative and value < 0:
        return None, "Error: Negative values are not allowed here."
    if value.adjusted() > 18:
        return None, "Error: Value is too large."

    return value, None


def format_decimal(value, precision):
    if precision == 0:
        quant = Decimal("1")
    else:
        quant = Decimal("1").scaleb(-precision)

    with localcontext() as ctx:
        ctx.prec = max(50, precision + 20)
        rounded = value.quantize(quant, rounding=ROUND_HALF_UP)

    output = format(rounded, "f")
    if "." in output:
        output = output.rstrip("0").rstrip(".")
    return output or "0"


def convert_length(value, from_unit, to_unit, precision):
    if value < 0:
        return None, "Error: Length cannot be negative."
    base_value = value * LENGTH_FACTORS[from_unit]
    result = base_value / LENGTH_FACTORS[to_unit]
    return format_decimal(result, precision), None


def convert_weight(value, from_unit, to_unit, precision):
    if value < 0:
        return None, "Error: Weight cannot be negative."
    base_value = value * WEIGHT_FACTORS[from_unit]
    result = base_value / WEIGHT_FACTORS[to_unit]
    return format_decimal(result, precision), None


def convert_temp(value, from_unit, to_unit, precision):
    absolute_zero = {
        "c": Decimal("-273.15"),
        "f": Decimal("-459.67"),
        "k": Decimal("0"),
    }
    if value < absolute_zero[from_unit]:
        return None, "Error: Temperature is below absolute zero."

    if from_unit == "f":
        celsius = (value - Decimal("32")) * Decimal("5") / Decimal("9")
    elif from_unit == "k":
        celsius = value - Decimal("273.15")
    else:
        celsius = value

    if to_unit == "f":
        result = (celsius * Decimal("9") / Decimal("5")) + Decimal("32")
    elif to_unit == "k":
        result = celsius + Decimal("273.15")
    else:
        result = celsius

    return format_decimal(result, precision), None


def convert_num(raw_value, from_unit, to_unit):
    value = raw_value.strip()
    if not value:
        return None, "Error: Please enter a value."
    if value.startswith("-"):
        return None, "Error: Number system values cannot be negative."
    if len(value) > MAX_NUMBER_SYSTEM_CHARS:
        return None, "Error: Value is too large."

    rules = {
        "bin": (2, re.compile(r"^[01]+$"), "Binary values can only contain 0 and 1."),
        "dec": (10, re.compile(r"^\d+$"), "Decimal values can only contain digits."),
        "hex": (16, re.compile(r"^[0-9a-fA-F]+$"), "Hexadecimal values can only contain 0-9 and A-F."),
    }
    base, pattern, message = rules[from_unit]
    if not pattern.fullmatch(value):
        return None, f"Error: {message}"

    if from_unit == "dec" and len(value) > 72:
        return None, "Error: Value is too large."

    try:
        decimal_value = int(value, base)
    except ValueError:
        return None, "Error: Invalid input."

    if decimal_value.bit_length() > 512:
        return None, "Error: Value is too large."

    if to_unit == "bin":
        result = bin(decimal_value)[2:]
    elif to_unit == "hex":
        result = hex(decimal_value)[2:].upper()
    else:
        result = str(decimal_value)

    if len(result) > MAX_RESULT_CHARS:
        return None, "Error: Result is too large to display safely."
    return result, None


def convert_value(category, raw_value, from_unit, to_unit, precision):
    try:
        if category == "num":
            return convert_num(raw_value, from_unit, to_unit)

        value, error = validate_decimal_input(raw_value, allow_negative=(category == "temp"))
        if error:
            return None, error

        if category == "length":
            return convert_length(value, from_unit, to_unit, precision)
        if category == "weight":
            return convert_weight(value, from_unit, to_unit, precision)
        if category == "temp":
            return convert_temp(value, from_unit, to_unit, precision)
    except (KeyError, InvalidOperation, OverflowError, ValueError):
        return None, "Error: Invalid conversion request."

    return None, "Error: Invalid conversion request."


def add_history(category, from_unit, to_unit, raw_value, result):
    from_label = UNIT_NAMES[from_unit]
    to_label = UNIT_NAMES[to_unit]
    history = session.get("history", [])
    if not isinstance(history, list):
        history = []

    history.insert(0, {
        "category": CATEGORY_OPTIONS[category]["label"],
        "label": f"{from_label} to {to_label}",
        "from_label": from_label,
        "to_label": to_label,
        "input_val": raw_value,
        "output_val": str(result),
    })

    session["history"] = history[:MAX_HISTORY_ITEMS]
    session.modified = True


@app.route("/", methods=["GET", "POST"])
def home():
    normalize_history()
    state = get_default_state()
    result = None
    error = None

    if request.method == "POST":
        state = sanitize_state(request.form)
        action = request.form.get("action", "convert")

        if action == "clear":
            session["history"] = []
            session.modified = True
            state["raw_val"] = ""
        else:
            result, error = convert_value(
                state["category"],
                state["raw_val"],
                state["from_unit"],
                state["to_unit"],
                state["precision"],
            )
            if result is not None:
                add_history(
                    state["category"],
                    state["from_unit"],
                    state["to_unit"],
                    state["raw_val"],
                    result,
                )

    history = session.get("history", [])
    return render_template(
        "website.html",
        result=result,
        error=error,
        history=history[:MAIN_HISTORY_ITEMS],
        full_history=history,
        remember_cat=state["category"],
        remember_from=state["from_unit"],
        remember_to=state["to_unit"],
        remember_val=state["raw_val"],
        precision=state["precision"],
        from_label=UNIT_NAMES.get(state["from_unit"], state["from_unit"]),
        to_label=UNIT_NAMES.get(state["to_unit"], state["to_unit"]),
        category_options=CATEGORY_OPTIONS,
    )


if __name__ == "__main__":
    app.run(debug=True)
