#!/usr/bin/env python3
"""Download official SCF microdata and estimate education-specific wealth.

The default is the October 2026 release: 13 cross-sections, 1989--2025,
already in 2025 dollars. Never silently mix releases or change the dollar base.
See METHODOLOGY.md for estimands, caveats, and the Fed's variance formula.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
FED = "https://www.federalreserve.gov"
RELEASE_YEAR = 2025
YEARS = list(range(1989, RELEASE_YEAR + 1, 3))
GROUPS = {"college": (4,), "hs_or_less": (1, 2), "some_college": (3,),
          "all_education": (1, 2, 3, 4), "no_hs": (1,), "hs_only": (2,)}
SAMPLES = ("children_at_home", "all_families")
Z95 = 1.959963984540054


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(v for k, v in attrs if k == "href" and v)


class Downloader:
    """Cache originals, freeze hashes, and stop if a source changes unexpectedly."""
    def __init__(self, data_dir: Path, offline=False, refresh=False):
        self.raw = data_dir / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.manifest_path = data_dir / "sources.json"
        self.manifest = (json.loads(self.manifest_path.read_text())
                         if self.manifest_path.exists() else {})
        self.offline, self.refresh = offline, refresh

    def get(self, relative: str, url: str) -> Path:
        path = self.raw / relative
        previous = self.manifest.get(relative)
        if path.exists() and not self.refresh:
            if previous and sha256(path) != previous["sha256"]:
                raise ValueError(f"Checksum mismatch for {path}; restore the original.")
            if not previous:
                raise ValueError(f"Unregistered cache file: {path}")
            return path
        if self.offline:
            raise FileNotFoundError(f"Offline mode: missing {path}; download from {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        # A normal browser-compatible header is needed by the Fed download server.
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (SCF academic reproducibility project)",
            "Referer": FED + "/econres/scfindex.htm"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    content = response.read()
                    final_url = response.geturl()
                break
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        digest = hashlib.sha256(content).hexdigest()
        if previous and digest != previous["sha256"] and not self.refresh:
            raise ValueError(f"Source changed: {url}. Review the new release; use --refresh explicitly.")
        if path.suffix == ".zip" and not zipfile.is_zipfile(io.BytesIO(content)):
            raise ValueError(f"Expected ZIP, received another content type: {url}")
        path.write_bytes(content)
        self.manifest[relative] = {
            "url": url, "resolved_url": final_url, "sha256": digest,
            "bytes": len(content),
            "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        return path

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2, sort_keys=True) + "\n")


def acquire(downloader: Downloader):
    """Discover extract/replicate links from the official survey landing pages."""
    pages = {}
    for year in YEARS:
        url = FED + ("/econres/scfindex.htm" if year == RELEASE_YEAR
                     else f"/econres/scf_{year}.htm")
        path = downloader.get(f"documentation/scf_{year}.html", url)
        html = path.read_text(errors="replace")
        bases = set(map(int, re.findall(r"inflation[- ]adjusted to\s+(20\d{2})\s+dollars", html, re.I)))
        if bases != {RELEASE_YEAR}:
            raise ValueError(f"{year}: expected only {RELEASE_YEAR}-dollar extracts; page reports {bases}.")
        if year == RELEASE_YEAR:
            latest = re.search(r"The\s+(20\d{2})\s+Survey of Consumer Finances.*?most recent", html, re.S)
            if not latest or int(latest.group(1)) != RELEASE_YEAR:
                raise ValueError("Latest release changed or could not be verified. Review sources before extending.")
        parser = Links()
        parser.feed(html)
        urls = [urllib.parse.urljoin(url, h) for h in parser.hrefs]
        extract = sorted({u for u in urls if re.search(fr"/scfp{year}excel\.zip$", u, re.I)})
        replicate = sorted({u for u in urls if re.search(r"/scf\d{2,4}rw1s\.zip$", u, re.I)})
        if len(extract) != 1 or len(replicate) != 1:
            raise ValueError(f"Cannot unambiguously identify official files for {year}: {extract}, {replicate}")
        pages[year] = {"extract": extract[0], "replicates": replicate[0]}
    downloads = [(f"extracts/scf_{y}.zip", pages[y]["extract"]) for y in YEARS]
    downloads += [(f"replicates/scf_{y}.zip", pages[y]["replicates"]) for y in YEARS]
    downloads += [
        ("documentation/bulletin.macro.txt", FED + "/econres/files/bulletin.macro.txt"),
        ("documentation/codebk2025.txt", FED + "/econres/files/codebk2025.txt"),
        ("documentation/Standard_Error_Documentation.pdf", FED + "/econres/files/Standard_Error_Documentation.pdf"),
        ("documentation/assignment.html", "https://polisci158-2026.github.io/section-03/index.html"),
        ("official/scf2025_tables_public_real_historical.xlsx", FED + "/econres/files/scf2025_tables_public_real_historical.xlsx"),
        ("validation/stlouis_dfa_2025.html", "https://www.stlouisfed.org/open-vault/2025/june/the-state-of-us-household-wealth")]

    def download_one(item):
        name, url = item
        path = downloader.get(name, url)
        return f"{name}: {path.stat().st_size:,} bytes"

    # Independent HTTP reads. Analysis is sequential by wave to bound memory use.
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for message in pool.map(download_one, downloads):
                print(message, flush=True)
    finally:
        downloader.save()
    return pages


def read_extract(path: Path, year: int) -> tuple[pd.DataFrame, str]:
    with zipfile.ZipFile(path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"Expected one CSV in {path}, found {members}")
        member = members[0]
        df = pd.read_csv(archive.open(member))
    df.columns = df.columns.str.lower()
    df["source_row"] = np.arange(len(df)) + 2  # header is CSV line 1
    id_col, family_col = ("x1", "xx1") if year == 1989 else ("y1", "yy1")
    required = [id_col, family_col, "wgt", "networth", "asset", "debt", "edcl",
                "kids", "famstruct", "age", "married"]
    if df[required].isna().any().any():
        raise ValueError(f"Missing required values in {year}")
    df = df[required + ["source_row"]].rename(columns={id_col: "record_id", family_col: "family_id"})
    df["implicate"] = (df.record_id - 10 * df.family_id).astype(int)
    df["year"] = year
    if set(df.implicate.unique()) != set(range(1, 6)):
        raise ValueError(f"Invalid implicate identifiers in {year}")
    if df.duplicated(["family_id", "implicate"]).any() or not df.groupby("family_id").size().eq(5).all():
        raise ValueError(f"Not exactly five records per family in {year}")
    if not (np.isfinite(df.wgt).all() and df.wgt.gt(0).all()):
        raise ValueError(f"Invalid weights in {year}")
    if not df.edcl.isin([1, 2, 3, 4]).all() or not df.kids.ge(0).all():
        raise ValueError(f"Invalid group codes in {year}")
    if not np.allclose(df.networth, df.asset - df.debt, rtol=1e-10, atol=0.02):
        raise ValueError(f"Net worth != assets - debt in {year}")
    if not df.kids.gt(0).equals(df.famstruct.isin([1, 4])):
        raise ValueError(f"KIDS and FAMSTRUCT disagree in {year}")
    return df, member


def weighted_stats(values, weights):
    """Mean and inverse-CDF median; do not interpolate across wealth values."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if values.ndim != 1 or weights.shape != values.shape:
        raise ValueError("Expected equally sized one-dimensional arrays")
    if not np.isfinite(values).all() or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Nonfinite values or negative weights")
    total = weights.sum()
    if total <= 0:
        raise ValueError("Empty weighted domain")
    order = np.argsort(values, kind="stable")
    crossing = np.searchsorted(np.cumsum(weights[order]), total / 2, side="left")
    return float(np.dot(values, weights) / total), float(values[order[crossing]])


def domain(df, sample, group):
    mask = df.edcl.isin(GROUPS[group])
    if sample == "children_at_home":
        mask &= df.kids.gt(0)
    return mask


def load_replicate_weights(path: Path, first: pd.DataFrame, year: int):
    """Join by record ID; actual bootstrap weight is WT1Bb * MMb, not WT1Bb."""
    with zipfile.ZipFile(path) as archive:
        member = next(n for n in archive.namelist() if n.lower().endswith(".dta"))
        rep = pd.read_stata(archive.open(member), convert_categoricals=False)
    rep.columns = rep.columns.str.lower()
    id_col = "x1" if year == 1989 else "y1"
    if rep[id_col].duplicated().any():
        raise ValueError(f"Duplicate replicate record identifiers in {year}")
    rep = rep.set_index(id_col).reindex(first.record_id.to_numpy())
    if rep.index.size != len(first) or rep.isna().all(axis=1).any():
        raise ValueError(f"Replicate join failed in {year}")
    wtcols = [f"wt1b{i}" for i in range(1, 1000)]
    mmcols = [f"mm{i}" for i in range(1, 1000)]
    weights = np.nan_to_num(rep[wtcols].to_numpy(dtype=float), nan=0.0).clip(min=0)
    multiplicities = np.nan_to_num(rep[mmcols].to_numpy(dtype=float), nan=0.0).clip(min=0)
    weights *= multiplicities
    if (weights.sum(axis=0) <= 0).any():
        raise ValueError(f"Empty replicate in {year}")
    return weights


def replicate_stats(values, weights):
    """Compute 999 bootstrap means and medians after sorting once per domain."""
    totals = weights.sum(axis=0)
    if (totals <= 0).any():
        raise ValueError("A bootstrap replicate has an empty domain")
    means = values @ weights / totals
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order], axis=0)
    indices = (cumulative >= totals[None, :] / 2).argmax(axis=0)
    medians = values[order][indices]
    return np.column_stack([means, medians])


def uncertainty(point, implicates, replicates, log_scale=False):
    """SCF MEANIT: Var_boot(first implicate) + (6/5)*Var(five estimates).

    Both sample variances use ddof=1 and are centered on their respective
    replicate/implicate averages, exactly as in the Fed's codebook macro.
    For ratios, apply this calculation to log ratios, then exponentiate.
    """
    imp = np.asarray(implicates)
    rep = np.asarray(replicates)
    if log_scale:
        if point <= 0 or (imp <= 0).any() or (rep <= 0).any():
            return dict(se=np.nan, ci_low=np.nan, ci_high=np.nan,
                        sampling_variance=np.nan, imputation_variance=np.nan)
        imp, rep = np.log(imp), np.log(rep)
    u, b = float(rep.var(ddof=1)), float(imp.var(ddof=1))
    se = float(np.sqrt(u + 1.2 * b))
    center = np.log(point) if log_scale else point
    low, high = center - Z95 * se, center + Z95 * se
    if log_scale:
        low, high = np.exp(low), np.exp(high)
    return dict(se=se, ci_low=float(low), ci_high=float(high),
                sampling_variance=u, imputation_variance=b)


def analyze_year(df, repweights, year, member):
    rows, gap_rows, implicate_rows, audit_rows = [], [], [], []
    first = df[df.implicate.eq(1)]
    for sample in SAMPLES:
        estimates, replicates = {}, {}
        groups = ["college", "hs_or_less", "some_college", "all_education"]
        if sample == "all_families":
            groups += ["no_hs", "hs_only"]
        for group in groups:
            selected = df[domain(df, sample, group)]
            impstats = []
            for implicate in range(1, 6):
                sub = selected[selected.implicate.eq(implicate)]
                mean, median = weighted_stats(sub.networth, sub.wgt)
                impstats.append((mean, median))
                implicate_rows.append(dict(year=year, sample=sample, group=group,
                    implicate=implicate, mean=mean, median=median,
                    weight_sum=float(sub.wgt.sum()),
                    weighted_networth_sum=float(np.dot(sub.wgt, sub.networth)),
                    n_families=len(sub)))
                if year in (1989, 2013, 2025) and sample == "children_at_home" and group in ("college", "hs_or_less"):
                    sorted_sub = sub.sort_values(["networth", "record_id"])
                    cumulative = sorted_sub.wgt.cumsum()
                    j = int(np.searchsorted(cumulative, sub.wgt.sum() / 2))
                    crossing = sorted_sub.iloc[j]
                    audit_rows.append(dict(year=year, group=group, implicate=implicate,
                        zip_member=member, n_families=len(sub),
                        sum_w=float(sub.wgt.sum()), sum_w_networth=float(np.dot(sub.wgt, sub.networth)),
                        mean=mean, median=median, median_record_id=int(crossing.record_id),
                        median_source_csv_row=int(crossing.source_row),
                        median_weight=float(crossing.wgt),
                        cdf_below=float(cumulative.iloc[j-1]/sub.wgt.sum()) if j else 0,
                        cdf_at=float(cumulative.iloc[j]/sub.wgt.sum())))
            estimates[group] = np.asarray(impstats)
            mask = domain(first, sample, group).to_numpy()
            replicates[group] = replicate_stats(first.networth.to_numpy()[mask], repweights[mask])
            # WGT is scaled by 1/5 in the extract. Scaling cancels within an
            # implicate; 5*mean(sum WGT) estimates the domain population.
            for k, statistic in enumerate(("mean", "median")):
                point = float(estimates[group][:, k].mean())
                unc = uncertainty(point, estimates[group][:, k], replicates[group][:, k])
                pooled = weighted_stats(selected.networth, selected.wgt)[k]
                rows.append(dict(year=year, dollar_base=RELEASE_YEAR, sample=sample,
                    group=group, statistic=statistic, estimate=point,
                    **unc, pooled_five_implicates=pooled,
                    n_unique_families=int(selected.family_id.nunique()),
                    n_families_min=int(selected.groupby("implicate").size().min()),
                    n_families_max=int(selected.groupby("implicate").size().max()),
                    estimated_families=float(selected.wgt.sum()), n_replicates=999))
        for k, statistic in enumerate(("mean", "median")):
            college = float(estimates["college"][:, k].mean())
            hs = float(estimates["hs_or_less"][:, k].mean())
            for measure in ("absolute_gap", "ratio"):
                if measure == "absolute_gap":
                    point = college - hs
                    imp = estimates["college"][:, k] - estimates["hs_or_less"][:, k]
                    rep = replicates["college"][:, k] - replicates["hs_or_less"][:, k]
                else:
                    point = college / hs if hs > 0 else np.nan
                    imp = estimates["college"][:, k] / estimates["hs_or_less"][:, k]
                    rep = replicates["college"][:, k] / replicates["hs_or_less"][:, k]
                gap_rows.append(dict(year=year, dollar_base=RELEASE_YEAR, sample=sample,
                    statistic=statistic, measure=measure, estimate=point,
                    **uncertainty(point, imp, rep, log_scale=measure == "ratio"),
                    se_scale="log_ratio" if measure == "ratio" else "dollars"))
    return rows, gap_rows, implicate_rows, audit_rows


def save_csv(df, path):
    """Stable numeric precision and gzip metadata allow hash-based rerun checks."""
    compression = {"method": "gzip", "mtime": 0} if str(path).endswith(".gz") else None
    df.to_csv(path, index=False, float_format="%.17g", compression=compression)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--offline", action="store_true", help="Use only checksum-verified cached originals")
    parser.add_argument("--refresh", action="store_true", help="Explicitly replace sources and their recorded hashes")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    if args.offline and args.refresh:
        parser.error("--offline and --refresh are mutually exclusive")
    downloader = Downloader(args.data_dir, args.offline, args.refresh)
    try:
        acquire(downloader)
    finally:
        # Also persist successful landing-page downloads if a later HTTP
        # request fails, so an interrupted first download can be resumed.
        downloader.save()
    if args.download_only:
        return
    out = args.data_dir / "processed"
    out.mkdir(parents=True, exist_ok=True)
    all_rows, all_gaps, all_imps, all_audits, clean, diagnostics = [], [], [], [], [], []
    for year in YEARS:
        df, member = read_extract(downloader.raw / f"extracts/scf_{year}.zip", year)
        repweights = load_replicate_weights(downloader.raw / f"replicates/scf_{year}.zip", df[df.implicate.eq(1)], year)
        rows, gaps, imps, audits = analyze_year(df, repweights, year, member)
        all_rows.extend(rows); all_gaps.extend(gaps); all_imps.extend(imps); all_audits.extend(audits)
        clean.append(df)
        diagnostics.append(dict(year=year, n_records=len(df), n_families=df.family_id.nunique(),
            max_accounting_error=float(np.abs(df.networth-df.asset+df.debt).max()),
            extract_population=float(df.wgt.sum()),
            replicate_population_min=float(repweights.sum(axis=0).min()),
            replicate_population_max=float(repweights.sum(axis=0).max()),
            negative_networth_records=int(df.networth.lt(0).sum()),
            education_varies_across_implicates=int(df.groupby("family_id").edcl.nunique().gt(1).sum()),
            kids_varies_across_implicates=int(df.groupby("family_id").kids.nunique().gt(1).sum())))
        print(f"Analyzed {year}: {df.family_id.nunique():,} families, five implicates, 999 replicates", flush=True)
    estimates = pd.DataFrame(all_rows)
    estimates["pct_change_since_1989"] = estimates.groupby(["sample", "group", "statistic"]).estimate.transform(lambda x: 100*(x/x.iloc[0]-1))
    gaps = pd.DataFrame(all_gaps)
    gaps["change_since_1989"] = gaps.groupby(["sample", "statistic", "measure"]).estimate.transform(lambda x: x-x.iloc[0])
    gaps["pct_change_since_1989"] = gaps.groupby(["sample", "statistic", "measure"]).estimate.transform(lambda x: 100*(x/x.iloc[0]-1))
    for name, frame in [("wealth_estimates.csv", estimates), ("wealth_gaps.csv", gaps),
                        ("implicate_estimates.csv", pd.DataFrame(all_imps)),
                        ("manual_audit.csv", pd.DataFrame(all_audits)),
                        ("diagnostics.csv", pd.DataFrame(diagnostics)),
                        ("clean_microdata.csv.gz", pd.concat(clean, ignore_index=True))]:
        save_csv(frame, out / name)
    print(f"Saved processed data to {out}")


if __name__ == "__main__":
    main()
