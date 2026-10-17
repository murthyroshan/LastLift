"""Fetch the station-layout files of every agency that publishes GTFS-Pathways (MS5, the Step-Free Atlas). Stdlib.

    python -I ingest/atlas_fetch.py      # catalogue -> data/raw/atlas/<feed id>/{pathways,stops,facilities,feed_info}.txt

Source: the Mobility Database catalogue (files.mobilitydatabase.org/feeds_v2.csv): active GTFS feeds whose features
include Pathways, no authentication, mirrors deduplicated. Only the needed members are fetched, by HTTP range
requests on the hosted zip (the zip's central directory, then each member's bytes), so a 100 MB feed costs a few MB.
Everything lands under data/raw/atlas/ (never committed); data/atlas_sources.json records ids, URLs, licences,
sizes and sha256 for reproducibility.
"""
import csv
import hashlib
import json
import struct
import sys
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "atlas"
WANT = ("pathways.txt", "stops.txt", "facilities.txt", "feed_info.txt", "levels.txt")
MIRRORS = {"mdb-3233": "mdb-782"}          # the same VBB feed listed twice: keep one


def http(url, rng=None):
    req = urllib.request.Request(url, headers={"User-Agent": "lastlift-atlas", **({"Range": rng} if rng else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()


def members(url):
    """{name: bytes} for the WANT members of a remote zip, using range requests."""
    status, head, tail = http(url, "bytes=-65536")
    size = int(head.get("content-range", "/0").split("/")[-1] or 0)
    if status != 206 or not size:
        raise RuntimeError("no range support")
    i = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[i + 12:i + 20])
    if cd_off == 0xFFFFFFFF:                       # zip64
        j = tail.rfind(b"PK\x06\x06")
        cd_size, cd_off = struct.unpack("<QQ", tail[j + 40:j + 56])
    _, _, cd = http(url, f"bytes={cd_off}-{cd_off + cd_size - 1}")
    out, p = {}, 0
    while p < len(cd) and cd[p:p + 4] == b"PK\x01\x02":
        method, = struct.unpack("<H", cd[p + 10:p + 12])
        csize, usize = struct.unpack("<II", cd[p + 20:p + 28])
        nlen, elen, clen = struct.unpack("<HHH", cd[p + 28:p + 34])
        off, = struct.unpack("<I", cd[p + 42:p + 46])
        name = cd[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        extra = cd[p + 46 + nlen:p + 46 + nlen + elen]
        if 0xFFFFFFFF in (csize, usize, off):      # zip64 extra field
            q, vals = 0, []
            while q < len(extra):
                hid, hlen = struct.unpack("<HH", extra[q:q + 4])
                if hid == 1:
                    vals = list(struct.unpack("<" + "Q" * (hlen // 8), extra[q + 4:q + 4 + hlen]))
                q += 4 + hlen
            if usize == 0xFFFFFFFF:
                usize = vals.pop(0)
            if csize == 0xFFFFFFFF:
                csize = vals.pop(0)
            if off == 0xFFFFFFFF:
                off = vals.pop(0)
        base = name.rsplit("/", 1)[-1]
        if base in WANT and base not in out:
            _, _, lh = http(url, f"bytes={off}-{off + 29}")
            ln, le = struct.unpack("<HH", lh[26:30])
            start = off + 30 + ln + le
            _, _, data = http(url, f"bytes={start}-{start + csize - 1}")
            out[base] = zlib.decompress(data, -15) if method == 8 else data
        p += 46 + nlen + elen + clen
    return out, size


def main():
    cat = RAW / "catalogue" / "feeds_v2.csv"
    rows = list(csv.DictReader(cat.open(encoding="utf-8")))
    feeds = [r for r in rows if r["data_type"] == "gtfs" and "Pathway" in (r.get("features") or "")
             and r["status"] in ("active", "") and not r.get("redirect.id")
             and r.get("urls.authentication_type") in ("", "0", None) and r["id"] not in MIRRORS]
    sources = []
    for r in feeds:
        url = r["urls.latest"] or r["urls.direct_download"]
        d = RAW / r["id"]
        d.mkdir(parents=True, exist_ok=True)
        try:
            got, size = members(url)
        except Exception as exc:                  # noqa: BLE001 - recorded, never fatal for the other feeds
            sources.append({"id": r["id"], "provider": r["provider"], "error": f"{type(exc).__name__}: {exc}"[:200]})
            print(r["id"], "ERROR", type(exc).__name__, flush=True)
            continue
        for name, data in got.items():
            (d / name).write_bytes(data)
        sources.append({"id": r["id"], "provider": r["provider"], "country": r["location.country_code"],
                        "url": url, "license": r.get("urls.license") or "", "zip_bytes": size,
                        "members": {n: hashlib.sha256(b).hexdigest() for n, b in sorted(got.items())}})
        print(r["id"], r["location.country_code"], {n: len(b) for n, b in got.items()}, flush=True)
    (ROOT / "data" / "atlas_sources.json").write_text(json.dumps(sources, indent=1, ensure_ascii=False) + "\n",
                                                      encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
