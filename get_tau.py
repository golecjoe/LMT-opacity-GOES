import os
import sys
import math
import csv
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

from fyodor import download_nc, rename_nc, pwv

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from python_script.goes_lv_query import get_goes_data  # noqa: E402

# start_date = "2025-12-27T00:00:00Z"
# end_date = "2025-12-27T01:00:00Z"


def fetch_goes_data(start_date,end_date,sat=19) -> None:
	sat = sat
	products = ["LVTP", "LVMP"]
	sector = "F"
	outdir = f"./goes_download_{sat}"

	matches = get_goes_data(
		sat=sat,
		products=products,
		sector=sector,
		start=start_date,
		end=end_date,
		download=True,
		outdir=outdir,
	)
	print(f"GOES fetch complete: {len(matches)} files processed")

def convert_pwv_to_tau(pwv,a=0.04,b=0.017):
	return (a*pwv)+b



if __name__ == "__main__":
	glob_start_date = "2026-09-04T01:00:00Z"
	glob_end_date = "2026-09-05T01:00:00Z"
	fetch_goes_data(glob_start_date,glob_end_date,sat=19)
	fetch_goes_data(glob_start_date,glob_end_date,sat=18)
	directory_19 = '/Users/golecjoe/Documents/Projects/pwv_project/tau_program/goes_download_19'
	directory_18 = '/Users/golecjoe/Documents/Projects/pwv_project/tau_program/goes_download_18'

	files_19 = sorted(Path(directory_19).glob("*.nc"))
	files_18 = sorted(Path(directory_18).glob("*.nc"))

	# print("Total files:", len(files))

	# for f in files:
	#     print(f.name)

	lvtp_files_19 = sorted([f for f in files_19 if "LVTP" in f.name])
	lvmp_files_19 = sorted([f for f in files_19 if "LVMP" in f.name])

	lvtp_files_18 = sorted([f for f in files_18 if "LVTP" in f.name])
	lvmp_files_18 = sorted([f for f in files_18 if "LVMP" in f.name])
	print('-----------------------------')
	print("GOES-19 LVTP files:", len(lvtp_files_19))
	print("GOES-19 LVMP files:", len(lvmp_files_19))
	print('-----------------------------')
	print("GOES-18 LVTP files:", len(lvtp_files_19))
	print("GOES-18 LVMP files:", len(lvmp_files_19))
	print('-----------------------------')
	# print("\nLVTP:")
	# for f in lvtp_files:
	#     print(f.name)

	# print("\nLVMP:")
	# for f in lvmp_files:
	#     print(f.name)

	# rename_nc(directory)
	location = 'LMT'
	P_min = 587#750
	P_max = 300
	line_of_sight = 'zenith'
	out_date_19, PWV_19, LVT_19, LVM_19 = pwv(directory_19, location, P_min,P_max, line_of_sight, RA=None, Dec=None,plot=False, csv=False)
	out_date_18, PWV_18, LVT_18, LVM_18 = pwv(directory_18, location, P_min,P_max, line_of_sight, RA=None, Dec=None,plot=False, csv=False)

	tau_19 = convert_pwv_to_tau(PWV_19)
	tau_18 = convert_pwv_to_tau(PWV_18)
	print('-----------------------------')
	print("GOES-19 Number of output times:", len(out_date_19))
	print("GOES-19 Number of PWV values:", len(PWV_19))

	print("\nFirst time:", out_date_19[0])
	print("Last time:", out_date_19[-1])
	print('-----------------------------')
	print("GOES-18 Number of output times:", len(out_date_18))
	print("GOES-18 Number of PWV values:", len(PWV_18))

	print("\nFirst time:", out_date_18[0])
	print("Last time:", out_date_18[-1])
	print('-----------------------------')
	# for d, p, t, m in zip(out_date, PWV, LVT, LVM):
	# 	print(
	# 		d,
	# 		"PWV =", p,
	# 		"LVT =", t,
	# 		"LVM =", m
	# 	)

	x_19 = [datetime.strptime(d, "%Y-%m-%d %H:%M:%S") for d in out_date_19]
	plot_start = datetime.strptime("2026-09-04 02:00:00", "%Y-%m-%d %H:%M:%S")
	plot_end = datetime.strptime("2026-09-05 00:00:00", "%Y-%m-%d %H:%M:%S")

	# Drop NaNs/None before plotting to avoid skewed limits.
	finite_pairs = [
		(t, v)
		for t, v in zip(x_19, tau_19)
		if (v is not None) and not (isinstance(v, float) and math.isnan(v))
	]
	if not finite_pairs:
		raise ValueError("No finite tau values to plot")

	x_plot_19, tau_plot_19 = zip(*finite_pairs)

	x_18 = [datetime.strptime(d, "%Y-%m-%d %H:%M:%S") for d in out_date_18]
	plot_start = datetime.strptime("2026-09-04 02:00:00", "%Y-%m-%d %H:%M:%S")
	plot_end = datetime.strptime("2026-09-05 00:00:00", "%Y-%m-%d %H:%M:%S")

	# Drop NaNs/None before plotting to avoid skewed limits.
	finite_pairs = [
		(t, v)
		for t, v in zip(x_18, tau_18)
		if (v is not None) and not (isinstance(v, float) and math.isnan(v))
	]
	if not finite_pairs:
		raise ValueError("No finite tau values to plot")

	x_plot_18, tau_plot_18 = zip(*finite_pairs)

	# Optionally export cleaned data.
	export_csv = True
	csv_path = Path(__file__).resolve().parent / "tau_export.csv"
	if export_csv:
		with open(csv_path, "w", newline="") as f:
			writer = csv.writer(f)
			writer.writerow(["timestamp", "tau"])
			for t, v in zip(x_plot_19, tau_plot_19):
				writer.writerow([t.isoformat(sep=" "), v])
		print(f"Wrote {len(x_plot_19)} rows to {csv_path}")

	# Plot
	fig, ax = plt.subplots()
	ax.plot(x_plot_19, tau_plot_19,'.',label='GOES-19 (East)')
	ax.plot(x_plot_18, tau_plot_18,'.',label='GOES-18 (WEST)')

	ax.set_xlim(plot_start, plot_end)

	# Auto-adjust y limits based only on points in the chosen date window.
	window_indices = [i for i, t in enumerate(x_plot_19) if plot_start <= t <= plot_end]
	if window_indices:
		y_window = [tau_plot_19[i] for i in window_indices]
		y_min = min(y_window)
		y_max = max(y_window)
		if y_min == y_max:
			pad = max(abs(y_min) * 0.1, 1)
		else:
			pad = (y_max - y_min) * 0.05
		ax.set_ylim(y_min - pad, y_max + pad)

	# Format datetime axis
	ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
	ax.xaxis.set_major_locator(mdates.AutoDateLocator())
	fig.autofmt_xdate()

	ax.set_xlabel("Date / Time")
	ax.set_ylabel(r"$\tau_{220}$")
	ax.set_title(f'Zenith Opacity')
	ax.legend()

	plt.show()
