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
            "km": "Kilometers (km)",
            "m": "Meters (m)",
            "cm": "Centimeters (cm)",
            "mm": "Millimeters (mm)",
            "in": "Inches (in)",
            "yd": "Yards (yd)",
            "mi": "Miles (mi)",
        },
    },
    "weight": {
        "label": "Weight",
        "default_from": "kg",
        "default_to": "lb",
        "units": {
            "t": "Tonnes (t)",
            "kg": "Kilograms (kg)",
            "g": "Grams (g)",
            "mg": "Milligrams (mg)",
            "lb": "Pounds (lb)",
            "oz": "Ounces (oz)",
            "st": "Stones (st)",
        },
    },
    "volume": {
        "label": "Liquid",
        "default_from": "l",
        "default_to": "gal",
        "units": {
            "l": "Liters (L)",
            "ml": "Milliliters (ml)",
            "fl_oz": "Fluid Ounces (fl oz)",
            "pt": "Pints (pt)",
            "qt": "Quarts (qt)",
            "gal": "Gallons (gal)",
        },
    },
    "temp": {
        "label": "Temperature",
        "default_from": "c",
        "default_to": "f",
        "units": {
            "c": "Celsius (°C)",
            "f": "Fahrenheit (°F)",
            "k": "Kelvin (K)",
        },
    },
    "time": {
        "label": "Time",
        "default_from": "h",
        "default_to": "min",
        "units": {
            "wk": "Weeks",
            "d": "Days",
            "h": "Hours",
            "min": "Minutes",
            "s": "Seconds",
        },
    },
    "speed": {
        "label": "Speed",
        "default_from": "km_h",
        "default_to": "m_s",
        "units": {
            "km_h": "Kilometers per hour (km/h)",
            "m_h": "Meters per hour (m/h)",
            "cm_h": "Centimeters per hour (cm/h)",
            "mi_h": "Miles per hour (mph)",
            "km_s": "Kilometers per sec (km/s)",
            "m_s": "Meters per sec (m/s)",
            "cm_s": "Centimeters per sec (cm/s)",
        },
    },
    "num": {
        "label": "Number Systems",
        "default_from": "dec",
        "default_to": "bin",
        "units": {
            "dec": "Decimal",
            "bin": "Binary",
            "oct": "Octal",
            "hex": "Hexadecimal",
        },
    },
}

UNIT_NAMES = {
    unit: label
    for category in CATEGORY_OPTIONS.values()
    for unit, label in category["units"].items()
}

# Base conversion maps
LENGTH_FACTORS = {
    "km": Decimal("1000"), "m": Decimal("1"), "cm": Decimal("0.01"), "mm": Decimal("0.001"),
    "in": Decimal("0.0254"), "yd": Decimal("0.9144"), "mi": Decimal("1609.344")
}
WEIGHT_FACTORS = {
    "t": Decimal("1000"), "kg": Decimal("1"), "g": Decimal("0.001"), "mg": Decimal("0.000001"),
    "lb": Decimal("0.45359237"), "oz": Decimal("0.028349523125"), "st": Decimal("6.35029318")
}
VOLUME_FACTORS = {
    "l": Decimal("1"), "ml": Decimal("0.001"),
    "fl_oz": Decimal("0.0295735295625"), "pt": Decimal("0.473176473"),
    "qt": Decimal("0.946352946"), "gal": Decimal("3.785411784")
}
TIME_FACTORS = {
    "wk": Decimal("604800"), "d": Decimal("86400"), "h": Decimal("3600"),
    "min": Decimal("60"), "s": Decimal("1")
}
SPEED_FACTORS = {
    "km_h": Decimal("1") / Decimal("3.6"), "m_h": Decimal("1") / Decimal("3600"),
    "cm_h": Decimal("1") / Decimal("360000"), "mi_h": Decimal("0.44704"),
    "km_s": Decimal("1000"), "m_s": Decimal("1"), "cm_s": Decimal("0.01")
}

NUMERIC_INPUT_PATTERN = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$")
SCIENTIFIC_INPUT_PATTERN = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d+$")
MAX_INPUT_CHARS = 80
MAX_DECIMAL_DIGITS = 24
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
    cleaned = [item for item in history if
               isinstance(item, dict) and {"label", "input_val", "output_val", "from_label", "to_label",
                                           "category"}.issubset(item)]
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

    if from_unit not in valid_units: from_unit = CATEGORY_OPTIONS[category]["default_from"]
    if to_unit not in valid_units: to_unit = CATEGORY_OPTIONS[category]["default_to"]

    raw_val = (form.get("value") or "").strip()
    if len(raw_val) > MAX_INPUT_CHARS and category != "num": raw_val = raw_val[:MAX_INPUT_CHARS]
    if len(raw_val) > MAX_NUMBER_SYSTEM_CHARS and category == "num": raw_val = raw_val[:MAX_NUMBER_SYSTEM_CHARS]

    precision = clamp_precision(form.get("precision", session.get("precision", 4)))
    session["precision"] = precision

    return {"category": category, "from_unit": from_unit, "to_unit": to_unit, "raw_val": raw_val,
            "precision": precision}


def validate_decimal_input(raw_value, allow_negative=False):
    if not raw_value: return None, "Error: Please enter a value."
    if SCIENTIFIC_INPUT_PATTERN.fullmatch(raw_value): return None, "Error: Scientific notation is not supported."
    if len(raw_value) > MAX_INPUT_CHARS: return None, "Error: Value is too large."
    if not NUMERIC_INPUT_PATTERN.fullmatch(raw_value): return None, "Error: Input must be a valid number."
    if sum(char.isdigit() for char in raw_value) > MAX_DECIMAL_DIGITS: return None, "Error: Value is too large."

    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        return None, "Error: Input must be a valid number."

    if not allow_negative and value < 0: return None, "Error: Negative values are not allowed here."
    if value.adjusted() > 24: return None, "Error: Value is too large."
    return value, None


def format_decimal(value, precision):
    quant = Decimal("1") if precision == 0 else Decimal("1").scaleb(-precision)
    with localcontext() as ctx:
        ctx.prec = max(50, precision + 30)
        rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    output = format(rounded, "f")
    if "." in output: output = output.rstrip("0").rstrip(".")
    return output or "0"


def generic_convert(value, from_unit, to_unit, factors, precision, error_msg="Value cannot be negative."):
    if value < 0: return None, f"Error: {error_msg}"
    base_value = value * factors[from_unit]
    result = base_value / factors[to_unit]
    return format_decimal(result, precision), None


def convert_temp(value, from_unit, to_unit, precision):
    absolute_zero = {"c": Decimal("-273.15"), "f": Decimal("-459.67"), "k": Decimal("0")}
    if value < absolute_zero[from_unit]: return None, "Error: Temperature is below absolute zero."

    celsius = (value - Decimal("32")) * Decimal("5") / Decimal("9") if from_unit == "f" else (
        value - Decimal("273.15") if from_unit == "k" else value)
    result = (celsius * Decimal("9") / Decimal("5")) + Decimal("32") if to_unit == "f" else (
        celsius + Decimal("273.15") if to_unit == "k" else celsius)

    return format_decimal(result, precision), None


def convert_num(raw_value, from_unit, to_unit):
    value = raw_value.strip()
    if not value: return None, "Error: Please enter a value."
    if value.startswith("-"): return None, "Error: Number system values cannot be negative."
    if len(value) > MAX_NUMBER_SYSTEM_CHARS: return None, "Error: Value is too large."

    rules = {
        "bin": (2, re.compile(r"^[01]+$"), "Binary values can only contain 0 and 1."),
        "oct": (8, re.compile(r"^[0-7]+$"), "Octal values can only contain digits 0-7."),
        "dec": (10, re.compile(r"^\d+$"), "Decimal values can only contain digits."),
        "hex": (16, re.compile(r"^[0-9a-fA-F]+$"), "Hexadecimal values can only contain 0-9 and A-F."),
    }
    base, pattern, message = rules[from_unit]
    if not pattern.fullmatch(value): return None, f"Error: {message}"
    if from_unit == "dec" and len(value) > 72: return None, "Error: Value is too large."

    try:
        decimal_value = int(value, base)
    except ValueError:
        return None, "Error: Invalid input."
    if decimal_value.bit_length() > 512: return None, "Error: Value is too large."

    result = bin(decimal_value)[2:] if to_unit == "bin" else (oct(decimal_value)[2:] if to_unit == "oct" else (
        hex(decimal_value)[2:].upper() if to_unit == "hex" else str(decimal_value)))
    if len(result) > MAX_RESULT_CHARS: return None, "Error: Result is too large to display safely."
    return result, None


def convert_value(category, raw_value, from_unit, to_unit, precision):
    try:
        if category == "num": return convert_num(raw_value, from_unit, to_unit)
        value, error = validate_decimal_input(raw_value, allow_negative=(category == "temp" or category == "speed"))
        if error: return None, error

        if category == "length": return generic_convert(value, from_unit, to_unit, LENGTH_FACTORS, precision,
                                                        "Length cannot be negative.")
        if category == "weight": return generic_convert(value, from_unit, to_unit, WEIGHT_FACTORS, precision,
                                                        "Weight cannot be negative.")
        if category == "volume": return generic_convert(value, from_unit, to_unit, VOLUME_FACTORS, precision,
                                                        "Volume cannot be negative.")
        if category == "time": return generic_convert(value, from_unit, to_unit, TIME_FACTORS, precision,
                                                      "Time cannot be negative.")
        if category == "speed": return generic_convert(value, from_unit, to_unit, SPEED_FACTORS, precision,
                                                       "Speed cannot be negative.")
        if category == "temp": return convert_temp(value, from_unit, to_unit, precision)
    except (KeyError, InvalidOperation, OverflowError, ValueError, ZeroDivisionError):
        return None, "Error: Invalid conversion request."
    return None, "Error: Invalid conversion request."


def add_history(category, from_unit, to_unit, raw_value, result):
    history = session.get("history", [])
    if not isinstance(history, list): history = []
    history.insert(0, {
        "category": CATEGORY_OPTIONS[category]["label"],
        "label": f"{UNIT_NAMES[from_unit]} to {UNIT_NAMES[to_unit]}",
        "from_label": UNIT_NAMES[from_unit],
        "to_label": UNIT_NAMES[to_unit],
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
            result, error = convert_value(state["category"], state["raw_val"], state["from_unit"], state["to_unit"],
                                          state["precision"])
            if result is not None:
                add_history(state["category"], state["from_unit"], state["to_unit"], state["raw_val"], result)

    history = session.get("history", [])
    return render_template(
        "website.html",
        result=result, error=error,
        history=history[:MAIN_HISTORY_ITEMS], full_history=history,
        remember_cat=state["category"], remember_from=state["from_unit"],
        remember_to=state["to_unit"], remember_val=state["raw_val"],
        precision=state["precision"],
        from_label=UNIT_NAMES.get(state["from_unit"], state["from_unit"]),
        to_label=UNIT_NAMES.get(state["to_unit"], state["to_unit"]),
        category_options=CATEGORY_OPTIONS,
    )


if __name__ == "__main__":
    app.run(debug=True)