#!/usr/bin/env python
"""Maintain a 48-hour GOES cache and plot LMT zenith opacity."""

from __future__ import annotations

import math
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from fyodor.fyodor import pwv  # noqa: E402
from goes_lv_query import get_goes_data, parse_goes_times_from_key  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / "goes_cache"
PLOTS_DIR = SCRIPT_DIR / "plots"


SATELLITES = (19, 18)
LOCATION = "LMT"
P_MIN = 587
P_MAX = 300
LINE_OF_SIGHT = "zenith"


@contextmanager
def preserve_working_directory() -> Iterator[None]:
    """Restore the working directory after a library call changes it."""
    original_directory = Path.cwd()
    try:
        yield
    finally:
        os.chdir(original_directory)


def fetch_goes_data(
    start_time: datetime,
    end_time: datetime,
    satellite: int,
    output_directory: Path,
) -> None:
    """Download full-disk temperature and moisture products for one satellite."""
    matches = get_goes_data(
        sat=satellite,
        products=["LVTP", "LVMP"],
        sector="F",
        start=start_time,
        end=end_time,
        download=True,
        outdir=str(output_directory),
    )

    matched_products = {product for product, _ in matches}
    missing_products = {"LVTP", "LVMP"} - matched_products
    if missing_products:
        missing = ", ".join(sorted(missing_products))
        raise RuntimeError(f"GOES-{satellite} returned no {missing} data")

    print(f"GOES-{satellite} fetch complete: {len(matches)} files processed")


def prune_cache(directory: Path, cutoff_time: datetime) -> int:
    """Delete cached GOES files observed before the UTC cutoff time."""
    if not directory.exists():
        return 0

    cutoff_utc = cutoff_time.astimezone(timezone.utc)
    removed_count = 0

    for file_path in directory.glob("*.nc"):
        file_times = parse_goes_times_from_key(file_path.name)
        if file_times is None:
            print(f"Keeping unrecognized cache file: {file_path.name}")
            continue

        if file_times.start < cutoff_utc:
            file_path.unlink()
            removed_count += 1

    print(f"Cache cleanup for {directory.name}: removed {removed_count} old files")
    return removed_count


def convert_pwv_to_tau(
    pwv_values: Sequence[float], a: float = 0.04, b: float = 0.017
) -> list[float]:
    """Convert precipitable water vapor in millimeters to tau at 220 GHz."""
    return [(a * float(value)) + b for value in pwv_values]


def calculate_tau(directory: Path, start_time: datetime, end_time: datetime):
    """Calculate finite tau values within the requested UTC time window."""
    # fyodor.pwv changes the process working directory, so contain that side effect.
    with preserve_working_directory():
        output_dates, pwv_values, _, _ = pwv(
            str(directory),
            LOCATION,
            P_MIN,
            P_MAX,
            LINE_OF_SIGHT,
            RA=None,
            Dec=None,
            plot=False,
            csv=False,
        )

    tau_values = convert_pwv_to_tau(pwv_values)
    finite_pairs = []
    for date_string, tau_value in zip(output_dates, tau_values):
        value = float(tau_value)
        timestamp_utc = datetime.strptime(
            date_string, "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        if math.isfinite(value) and start_time <= timestamp_utc < end_time:
            finite_pairs.append((timestamp_utc.replace(tzinfo=None), value))

    if not finite_pairs:
        raise ValueError(f"No finite tau values were calculated from {directory}")

    timestamps, tau_values = zip(*finite_pairs)
    return tuple(timestamps), tuple(tau_values)


def save_plot(
    series_by_satellite: dict[int, tuple[Sequence[datetime], Sequence[float]]],
    start_time: datetime,
    end_time: datetime,
    output_path: Path,
) -> None:
    """Plot both satellites over the query window and save the figure."""
    plot_start = start_time.astimezone(timezone.utc).replace(tzinfo=None)
    plot_end = end_time.astimezone(timezone.utc).replace(tzinfo=None)

    fig, ax = plt.subplots(figsize=(11, 6))
    labels = {19: "GOES-19 (East)", 18: "GOES-18 (West)"}
    colors = {19: "tab:blue", 18: "tab:orange"}

    window_tau = []
    for satellite in SATELLITES:
        timestamps, tau_values = series_by_satellite[satellite]
        ax.plot(
            timestamps,
            tau_values,
            ".",
            color=colors[satellite],
            label=labels[satellite],
        )
        window_tau.extend(
            value
            for timestamp, value in zip(timestamps, tau_values)
            if plot_start <= timestamp <= plot_end
        )

    ax.set_xlim(plot_start, plot_end)
    if window_tau:
        y_min = min(window_tau)
        y_max = max(window_tau)
        pad = max((y_max - y_min) * 0.05, abs(y_min) * 0.01, 0.001)
        ax.set_ylim(y_min - pad, y_max + pad)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()
    ax.set_xlabel("Date / Time (UTC)")
    ax.set_ylabel(r"$\tau_{220}$")
    ax.set_title("LMT Zenith Opacity — Previous 48 Hours")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def update_current_plot_symlink(plot_path: Path) -> Path:
    """Atomically point current_plot.png at the newly generated plot."""
    current_plot_path = plot_path.parent / "current_plot.png"
    if current_plot_path.exists() and not current_plot_path.is_symlink():
        raise FileExistsError(
            f"Refusing to replace non-symlink file: {current_plot_path}"
        )

    temporary_link = plot_path.parent / f".current_plot.{os.getpid()}.tmp"
    try:
        temporary_link.unlink(missing_ok=True)
        temporary_link.symlink_to(plot_path.name)
        os.replace(temporary_link, current_plot_path)
    finally:
        temporary_link.unlink(missing_ok=True)

    return current_plot_path


def main() -> None:
    run_time = datetime.now(timezone.utc).replace(microsecond=0)
    start_time = run_time - timedelta(hours=48)
    run_timestamp = run_time.strftime("%Y%m%dT%H%M%SZ")

    print(f"Query window: {start_time.isoformat()} to {run_time.isoformat()}")

    series_by_satellite = {}

    for satellite in SATELLITES:
        satellite_directory = CACHE_DIR / f"goes_{satellite}"
        satellite_directory.mkdir(parents=True, exist_ok=True)
        prune_cache(satellite_directory, start_time)
        fetch_goes_data(start_time, run_time, satellite, satellite_directory)
        timestamps, tau_values = calculate_tau(
            satellite_directory, start_time, run_time
        )
        series_by_satellite[satellite] = (timestamps, tau_values)

    plot_path = PLOTS_DIR / f"tau_last_48h_{run_timestamp}.png"
    save_plot(series_by_satellite, start_time, run_time, plot_path)
    current_plot_path = update_current_plot_symlink(plot_path)
    print(f"Saved plot to {plot_path}")
    print(f"Updated current plot link: {current_plot_path} -> {plot_path.name}")


if __name__ == "__main__":
    main()
