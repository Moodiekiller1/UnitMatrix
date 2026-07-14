from flask import Flask, render_template, request, session

app = Flask(__name__)
# Secret key ensures user sessions are fully locked down and private
app.secret_key = 'unitmatrix_super_secret_key_swapnil_v1.3'

# Dictionary translation system to make history entries look premium
UNIT_NAMES = {
    'km': 'Kilometers', 'm': 'Meters', 'cm': 'Centimeters', 'mm': 'Millimeters',
    't': 'Tonnes', 'kg': 'Kilograms', 'g': 'Grams', 'mg': 'Milligrams',
    'c': 'Celsius', 'f': 'Fahrenheit', 'k': 'Kelvin',
    'dec': 'Decimal', 'bin': 'Binary', 'hex': 'Hexadecimal'
}


# ==========================================
# BACKEND CONVERTER LOGIC (Written by Me!)
# ==========================================

def convert_length(value, from_unit, to_unit):
    if value < 0:
        return "Error: Length cannot be negative!"
    factors = {'km': 1000, 'm': 1, 'cm': 0.01, 'mm': 0.001}
    base_value = value * factors[from_unit]
    return round(base_value / factors[to_unit], 4)


def convert_weight(value, from_unit, to_unit):
    if value < 0:
        return "Error: Weight cannot be negative!"
    factors = {'t': 1000, 'kg': 1, 'g': 0.001, 'mg': 0.000001}
    base_value = value * factors[from_unit]
    return round(base_value / factors[to_unit], 4)


def convert_temp(value, from_unit, to_unit):
    if from_unit == 'c' and value < -273.15:
        return "Error: Below Absolute Zero (-273.15°C)!"
    if from_unit == 'k' and value < 0:
        return "Error: Below Absolute Zero (0 K)!"
    if from_unit == 'f' and value < -459.67:
        return "Error: Below Absolute Zero (-459.67°F)!"

    if from_unit == to_unit:
        return round(value, 4)

    if from_unit == 'f':
        celsius = (value - 32) * 5 / 9
    elif from_unit == 'k':
        celsius = value - 273.15
    else:
        celsius = value

    if to_unit == 'f':
        return round((celsius * 9 / 5) + 32, 4)
    elif to_unit == 'k':
        return round(celsius + 273.15, 4)
    else:
        return round(celsius, 4)


def convert_num(value_str, from_unit, to_unit):
    val_clean = str(value_str).strip()
    if not val_clean:
        return "Error: Empty value"
    if '-' in val_clean:
        return "Error: Number system values cannot be negative!"

    try:
        if from_unit == 'bin':
            if not all(c in '01' for c in val_clean):
                return "Error: Invalid Binary digits!"
            dec_val = int(val_clean, 2)
        elif from_unit == 'hex':
            if not all(c in '0123456789abcdefABCDEF' for c in val_clean):
                return "Error: Invalid Hexadecimal digits!"
            dec_val = int(val_clean, 16)
        else:
            dec_val = int(val_clean, 10)

        if to_unit == 'bin':
            return bin(dec_val)[2:]
        elif to_unit == 'hex':
            return hex(dec_val)[2:].upper()
        else:
            return str(dec_val)
    except Exception:
        return "Error: Out of bounds or invalid format"


# ==========================================
# MAIN ROUTE HANDLER
# ==========================================

@app.route('/', methods=['GET', 'POST'])
def home():
    # Automatically clear out legacy formatted arrays from older patches to prevent crash loops
    if 'history' not in session or (session['history'] and isinstance(session['history'][0], str)):
        session['history'] = []

    result = None
    category = 'length'
    from_unit = 'km'
    to_unit = 'm'
    raw_val = ''

    if request.method == 'POST':
        # Safely preserve user parameters across state switches
        category = request.form.get('category', 'length')
        from_unit = request.form.get('from_unit', 'km')
        to_unit = request.form.get('to_unit', 'm')
        raw_val = request.form.get('value', '').strip()

        if request.form.get('action') == 'clear':
            session['history'] = []
            session.modified = True
            raw_val = ''  # Wipe current card valuation view on hard clear state
        else:
            if raw_val:
                if category == 'num':
                    result = convert_num(raw_val, from_unit, to_unit)
                else:
                    try:
                        numeric_value = float(raw_val)
                        if category == 'length':
                            result = convert_length(numeric_value, from_unit, to_unit)
                        elif category == 'weight':
                            result = convert_weight(numeric_value, from_unit, to_unit)
                        elif category == 'temp':
                            result = convert_temp(numeric_value, from_unit, to_unit)
                    except ValueError:
                        result = "Error: Input must be a valid number."

                # Update history structured map up to 10 entries cleanly
                if result is not None and not str(result).startswith("Error"):
                    from_pretty = UNIT_NAMES.get(from_unit, from_unit)
                    to_pretty = UNIT_NAMES.get(to_unit, to_unit)

                    history_entry = {
                        'label': f"Converted {from_pretty} to {to_pretty}:",
                        'input_val': raw_val,
                        'output_val': str(result)
                    }

                    history_list = session['history']
                    history_list.insert(0, history_entry)
                    if len(history_list) > 10:
                        history_list.pop()
                    session['history'] = history_list
                    session.modified = True

    return render_template('website.html',
                           result=result,
                           history=session.get('history', []),
                           remember_cat=category,
                           remember_from=from_unit,
                           remember_to=to_unit,
                           remember_val=raw_val)


if __name__ == '__main__':
    app.run(debug=True)