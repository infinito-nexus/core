import datetime
import subprocess
import sys


def hex_to_rgb(hex_color):
    """Converts a hexadecimal color string to an RGB tuple.

    Args:
        hex_color (str): Hexadecimal color string.

    Returns:
        tuple: Tuple representing the RGB color.
    """
    if len(hex_color) != 6:
        raise ValueError("Hex color must be 6 characters long.")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def calculate_color(start_color, end_color, ratio):
    """Calculates the interpolated color between two colors.

    Args:
        start_color (str): Start color in hex format.
        end_color (str): End color in hex format.
        ratio (float): Interpolation ratio (0 to 1).

    Returns:
        str: Interpolated color in hex format.
    """
    start_rgb = hex_to_rgb(start_color)
    end_rgb = hex_to_rgb(end_color)
    current_rgb = [
        round(start + (end - start) * ratio)
        for start, end in zip(start_rgb, end_rgb, strict=False)
    ]
    return "".join(f"{value:02x}" for value in current_rgb)


def get_current_period(current_time, color_times):
    """
    Determines the current time period and returns the corresponding colors.

    Args:
    current_time (datetime.time): The current time.
    color_times (dict): A dictionary linking time periods (as a string in 'HH:MM' format)
                        with pairs of colors.

    Returns:
    tuple: A tuple of the start and end color (as hex codes) for the current period.
    """
    sorted_periods = sorted(color_times.items())
    for i, (period_start_str, _colors) in enumerate(sorted_periods):
        period_start_time = datetime.datetime.strptime(  # noqa: DTZ007  HH:MM is local time-of-day; no timezone applies
            period_start_str, "%H:%M"
        ).time()
        if current_time <= period_start_time:
            return sorted_periods[i - 1 if i > 0 else -1][1]
    return sorted_periods[0][1]


def calculate_transition_ratio(current_time, start_time, end_time):
    """
    Calculates the transition ratio for a color transition.

    Args:
    current_time (datetime.time): The current time.
    start_time (datetime.time): The start time of the current color period.
    end_time (datetime.time): The end time of the current color period.

    Returns:
    float: The transition ratio between 0 and 1.
    """
    # Use the current date for timestamp calculation
    today = datetime.datetime.now().date()  # noqa: DTZ005  user's local "today" for time-of-day color picking

    # Calculate timestamps for the start and end of the current period
    start_timestamp = datetime.datetime.combine(today, start_time).timestamp()
    end_timestamp = datetime.datetime.combine(today, end_time).timestamp()

    # If start and end times are the same, return 0 to indicate no transition
    if start_timestamp == end_timestamp:
        return 0

    # Calculate the current timestamp
    current_timestamp = datetime.datetime.combine(today, current_time).timestamp()

    # Calculate the transition ratio
    transition_duration = end_timestamp - start_timestamp
    time_since_start = current_timestamp - start_timestamp

    # Ratio as the proportion of time elapsed in the total transition duration
    return time_since_start / transition_duration


def change_keyboard_color(color, device_id):
    """Changes the keyboard color using an external command.

    Args:
        color (str): Color in hex format.
        device_id (str): Vendor and product ID for the keyboard.
    """
    command = ["msi-perkeyrgb", "--model", "GS65", "-s", color, "--id", device_id]
    try:
        subprocess.run(command, check=True)
        print(f"Keyboard color changed to #{color}.")
    except subprocess.CalledProcessError as e:
        print(f"Error setting keyboard color: {e}")
        sys.exit(1)


def main(vendor_and_product_id):
    color_times = {
        "22:00": ("990000", "990000"),  # Night
        "21:00": ("0000ff", "990000"),  # Evening Blue to Night
        "20:00": ("fdbe51", "0000ff"),  # Evening Golden to Blue
        "19:30": ("ff4500", "fdbe51"),  # Sunset to Golden
        "12:00": ("ffffff", "ff4500"),  # Noon to Sunset
        "07:30": ("ffd700", "ffffff"),  # Sunrise to Noon
        "07:00": ("f9c80e", "ffd700"),  # Morning Golden to Sunrise
        "06:00": ("ff7f00", "f9c80e"),  # Dawn to Golden
        "05:00": ("5bc0eb", "ff7f00"),  # Morning Blue to Dawn
        "04:00": ("990000", "5bc0eb"),  # Night to Blue
    }

    current_time = datetime.datetime.now().time()  # noqa: DTZ005  user's local time-of-day for color picking
    start_color, end_color = get_current_period(current_time, color_times)

    sorted_times = sorted(color_times.keys())
    for time_str in [*sorted_times, sorted_times[0]]:
        next_start_time_obj = datetime.datetime.strptime(  # noqa: DTZ007  HH:MM is local time-of-day; no timezone applies
            time_str, "%H:%M"
        ).time()
        if current_time < next_start_time_obj:
            break

    current_period_start_time_str = next(
        time
        for time, colors in color_times.items()
        if colors == (start_color, end_color)
    )
    current_period_start_time_obj = datetime.datetime.strptime(  # noqa: DTZ007  HH:MM is local time-of-day; no timezone applies
        current_period_start_time_str, "%H:%M"
    ).time()

    transition_ratio = calculate_transition_ratio(
        current_time, current_period_start_time_obj, next_start_time_obj
    )
    current_color = calculate_color(start_color, end_color, transition_ratio)

    change_keyboard_color(current_color, vendor_and_product_id)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Error: Vendor and product ID is missing.")
        print("Usage: python keyboard_color.py <vendor_and_product_id>")
        sys.exit(1)

    vendor_and_product_id = sys.argv[1]
    main(vendor_and_product_id)
