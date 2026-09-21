#!/usr/bin/env python3

import argparse
import datetime as dt
import os
import re
from collections import namedtuple
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import s3fs


def parse_utc(timestr):
    """Parse an ISO-like UTC timestamp into a timezone-aware datetime."""
    s = timestr.strip()

    # Handle a trailing Z as UTC.
    if s.endswith("Z"):
        s = s[:-1]

    s = s.replace(" ", "T")

    # Python 3.5 does not have datetime.fromisoformat(), so parse the
    # common formats used by this script explicitly.
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ]

    parsed = None
    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(s, fmt)
            break
        except ValueError:
            pass

    if parsed is None:
        raise ValueError("Could not parse UTC datetime: {}".format(timestr))

    return parsed.replace(tzinfo=dt.timezone.utc)


def datetime_to_year_doy(t):
    t = t.astimezone(dt.timezone.utc)
    return t.year, int(t.strftime("%j"))


def iter_day_starts(start, end):
    s = start.astimezone(dt.timezone.utc)
    e = end.astimezone(dt.timezone.utc)
    day = dt.datetime(s.year, s.month, s.day, tzinfo=dt.timezone.utc)
    while day < e:
        yield day
        day += dt.timedelta(days=1)


# dataclasses were introduced in Python 3.7, so use a namedtuple instead.
GoesFileTimes = namedtuple("GoesFileTimes", ["start", "end", "created"])


_TIME_RE = re.compile(
    r"_s(?P<s>\d{4}\d{3}\d{6})\d"
    r"(?:_e(?P<e>\d{4}\d{3}\d{6})\d)?"
    r"(?:_c(?P<c>\d{4}\d{3}\d{6})\d)?"
)


def _parse_yyyyjjjhhmmss(token):
    year = int(token[0:4])
    jjj = int(token[4:7])
    hh = int(token[7:9])
    mm = int(token[9:11])
    ss = int(token[11:13])
    t0 = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=jjj - 1)
    return t0.replace(hour=hh, minute=mm, second=ss)


def parse_goes_times_from_key(s3_key):
    m = _TIME_RE.search(s3_key)
    if not m:
        return None
    s_tok = m.group("s")
    e_tok = m.group("e")
    c_tok = m.group("c")
    start = _parse_yyyyjjjhhmmss(s_tok)
    end = _parse_yyyyjjjhhmmss(e_tok) if e_tok else None
    created = _parse_yyyyjjjhhmmss(c_tok) if c_tok else None
    return GoesFileTimes(start=start, end=end, created=created)


def build_day_prefix(product, sector, day_start):
    """
    IMPORTANT: GOES buckets are partitioned: PRODUCT/YYYY/DOY/HH/<files>.nc
    We list at PRODUCT/YYYY/DOY/ and recurse.
    """
    product = product.upper()
    sector = sector.upper()
    year, doy = datetime_to_year_doy(day_start)
    return "ABI-L2-{}{}{}/{:04d}/{:03d}/".format(
        product, sector, "", year, doy
    )


def find_nc_objects_under(fs, bucket, day_prefix):
    """
    Recursively find .nc objects under bucket/day_prefix.
    Returns keys relative to bucket, e.g. 'ABI-L2-LVTPF/2024/351/00/OR_...nc'
    """
    root = "{}/{}".format(bucket, day_prefix)
    try:
        found = fs.find(root)
    except FileNotFoundError:
        return []
    except Exception as e:
        raise RuntimeError(
            "Failed to find under s3://{}: {}".format(root, e)
        )

    out = []
    for p in found:
        if not p.endswith(".nc"):
            continue
        if p.startswith(bucket + "/"):
            out.append(p[len(bucket) + 1:])
        else:
            out.append(p)
    return out


def filter_keys_by_timerange(keys, t_start, t_end):
    out = []
    for k in keys:
        times = parse_goes_times_from_key(k)
        if times is None:
            continue
        if (times.start >= t_start) and (times.start < t_end):
            out.append(k)
    return sorted(out)


def download_keys(fs, bucket, keys, outdir):
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    for k in keys:
        fname = os.path.basename(k)
        src = "{}/{}".format(bucket, k)
        dst = os.path.join(outdir, fname)

        if os.path.exists(dst):
            print("[skip] {} exists".format(dst))
            continue

        print("[get ] s3://{} -> {}".format(src, dst))
        fs.get(src, dst)


def get_goes_data(
    sat,
    products,
    sector,
    start,
    end,
    download=False,
    outdir="./goes_download",
):
    """Query GOES LVTP/LVMP objects and optionally download them."""
    t0 = parse_utc(start) if isinstance(start, str) else start
    t1 = parse_utc(end) if isinstance(end, str) else end

    if t1 <= t0:
        raise ValueError("--end must be after --start")

    bucket = "noaa-goes{}".format(sat)
    fs = s3fs.S3FileSystem(anon=True)

    all_matches = []
    for prod in products:
        prod_upper = prod.upper()
        all_day_keys = []

        for day in iter_day_starts(t0, t1):
            day_prefix = build_day_prefix(prod_upper, sector, day)
            all_day_keys.extend(
                find_nc_objects_under(fs, bucket, day_prefix)
            )

        matches = filter_keys_by_timerange(all_day_keys, t0, t1)
        for k in matches:
            all_matches.append((prod_upper, k))

    if not all_matches:
        print("No matches found.")
        print("Try:")
        print("  - switching satellites: --sat 18")
        print("  - switching sectors: --sector C (CONUS) or F (Full Disk)")
        print("  - widening the window (full day is fine)")
        return []

    print("Found {} files:".format(len(all_matches)))
    for prod, k in all_matches:
        times = parse_goes_times_from_key(k)
        tstr = times.start.isoformat() if times else "?"
        print("  {}  {}  s3://{}/{}".format(prod, tstr, bucket, k))

    if download:
        for prod in sorted(set(p for p, _ in all_matches)):
            keys = [k for p, k in all_matches if p == prod]
            download_keys(fs, bucket, keys, outdir)

    return all_matches


def main():
    ap = argparse.ArgumentParser(
        description="Query GOES ABI LVTP/LVMP from NOAA public AWS S3."
    )
    ap.add_argument("--sat", type=int, choices=[16, 17, 18, 19], default=16)
    ap.add_argument(
        "--product",
        nargs="+",
        choices=["LVTP", "LVMP"],
        required=True,
    )
    ap.add_argument(
        "--sector",
        type=str,
        choices=["F", "C", "M1", "M2"],
        default="F",
    )
    ap.add_argument("--start", type=str, required=True)
    ap.add_argument("--end", type=str, required=True)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--outdir", type=str, default="./goes_download")

    args = ap.parse_args()

    get_goes_data(
        sat=args.sat,
        products=args.product,
        sector=args.sector,
        start=args.start,
        end=args.end,
        download=args.download,
        outdir=args.outdir,
    )


if __name__ == "__main__":
    main()
