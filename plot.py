#!/usr/bin/env python3
"""Render publication figures using only calculated, processed SCF estimates."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import textwrap

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT/".mplconfig"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np
import pandas as pd

BASE = 2025
FIXED_DATE = datetime(2026, 10, 16, tzinfo=timezone.utc)
SOURCE = "Source: Federal Reserve Board, Survey of Consumer Finances, 1989–2025 public summary extracts."
NOTES = ("Notes: Families with children living at home (KIDS>0; children may be adults). Education is the SCF reference "
         "person’s: bachelor’s or higher versus high school/GED or less; some college/associate degrees excluded. "
         "Survey-weighted estimates are averaged over five implicates. Whiskers show approximate pointwise 95% CIs "
         "using 999 design bootstrap replicates plus imputation variance. Extracts already use 2025 dollars.")


def style():
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 10,
        "axes.labelsize": 11, "axes.linewidth": .65,
        "xtick.labelsize": 9, "ytick.labelsize": 10,
        "pdf.fonttype": 42, "ps.fonttype": 42,
        "savefig.facecolor": "white", "figure.facecolor": "white"})


def save(fig, name, directory):
    directory.mkdir(parents=True, exist_ok=True)
    fig.savefig(directory/f"{name}.png", dpi=450, metadata={"Software": "ps158-reproduce; Matplotlib"})
    fig.savefig(directory/f"{name}.pdf", metadata={"Title": name,
        "Author": "POLISCI 158 research project", "CreationDate": FIXED_DATE, "ModDate": FIXED_DATE})
    plt.close(fig)
    print(f"Saved {name}.png and .pdf")


def axes_style(ax, years, scale, step, upper):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(".25")
    ax.grid(axis="y", color=".89", linewidth=.55)
    ax.set_axisbelow(True)
    ax.set_xlim(years.min()-1, years.max()+1)
    ax.set_xticks(years)
    ax.tick_params(axis="both", length=3, width=.6)
    ax.set_ylim(0, upper)
    ax.yaxis.set_major_locator(MultipleLocator(step))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x/scale:,.1f}" if scale==1e6 else f"{x/scale:,.0f}"))
    ax.set_xlabel("SCF survey year", labelpad=8)


def footer(fig, number, caption, notes=NOTES):
    caption = textwrap.fill(f"Figure {number}. {caption}", 100)
    fig.text(.105, .255, caption, fontsize=10.5, weight="bold", va="top", linespacing=1.4)
    fig.text(.105, .177, SOURCE, fontsize=8.2, va="top")
    fig.text(.105, .143, textwrap.fill(notes, 125), fontsize=8.2, va="top", linespacing=1.5)


def group_chart(estimates, statistic, number, directory):
    sub = estimates[(estimates["sample"]=="children_at_home") &
                    (estimates.statistic==statistic)]
    fig = plt.figure(figsize=(10, 7.3))
    ax = fig.add_axes([.105, .365, .855, .595])
    years = np.sort(sub.year.unique())
    selected = sub[sub.group.isin(["college", "hs_or_less"])]
    scale, step = (1e6, .5e6) if statistic=="mean" else (1e3, 100e3)
    upper = np.ceil(selected.ci_high.max()/step)*step
    axes_style(ax, years, scale, step, upper)
    for group, label, marker, linestyle, face in [
        ("college", "Bachelor’s degree or higher", "o", "-", "black"),
        ("hs_or_less", "High school/GED or less", "s", "--", "white")]:
        s = sub[sub.group==group].sort_values("year")
        ax.errorbar(s.year, s.estimate,
            yerr=np.vstack([s.estimate-s.ci_low, s.ci_high-s.estimate]),
            fmt="none", ecolor=".55", elinewidth=.7, capsize=2, capthick=.7, zorder=1)
        ax.plot(s.year, s.estimate, color="black", marker=marker, linestyle=linestyle,
            markerfacecolor=face, markeredgewidth=.9, markersize=5,
            linewidth=1.5, label=label, zorder=3)
    ax.set_ylabel(f"{statistic.capitalize()} family net worth\n({ 'millions' if statistic=='mean' else 'thousands'} of 2025 dollars)", labelpad=12)
    ax.legend(loc="upper left", frameon=False, fontsize=10, handlelength=3)
    footer(fig, number, f"{statistic.capitalize()} family net worth by parents’ educational attainment, 1989–2025.")
    save(fig, f"figure_{number}_{statistic}_wealth", directory)


def gap_chart(gaps, directory):
    sub = gaps[(gaps["sample"]=="children_at_home") & (gaps.measure=="absolute_gap")]
    fig = plt.figure(figsize=(10, 7.3)); ax=fig.add_axes([.105, .365, .855, .595])
    years=np.sort(sub.year.unique()); step=.5e6
    axes_style(ax, years, 1e6, step, np.ceil(sub.ci_high.max()/step)*step)
    for stat, label, marker, ls, face in [("mean", "Difference in means", "o", "-", "black"),
                                          ("median", "Difference in medians", "s", "--", "white")]:
        s=sub[sub.statistic==stat].sort_values("year")
        ax.errorbar(s.year,s.estimate,yerr=np.vstack([s.estimate-s.ci_low,s.ci_high-s.estimate]),
                    fmt="none",ecolor=".55",elinewidth=.7,capsize=2,capthick=.7,zorder=1)
        ax.plot(s.year,s.estimate,color="black",marker=marker,linestyle=ls,markerfacecolor=face,
                markersize=5,linewidth=1.5,label=label,zorder=3)
    ax.set_ylabel("College minus HS-or-less net worth\n(millions of 2025 dollars)",labelpad=12)
    ax.legend(loc="upper left",frameon=False,handlelength=3)
    footer(fig,3,"The absolute educational wealth gap among families with children, 1989–2025.")
    save(fig,"figure_3_absolute_gap",directory)


def economist_chart(estimates,gaps,directory):
    plt.rcParams.update({"font.family":"DejaVu Sans"})
    sub=estimates[(estimates["sample"]=="children_at_home") & (estimates.statistic=="mean")]
    latest_gap=gaps[(gaps["sample"]=="children_at_home") & (gaps.statistic=="mean") &
                     (gaps.measure=="absolute_gap") & (gaps.year==BASE)].iloc[0].estimate
    bg="#f4f4ef"; fig=plt.figure(figsize=(10.5,7.3),facecolor=bg)
    ax=fig.add_axes([.07,.265,.85,.54],facecolor=bg)
    fig.text(.07,.947,f"A ${latest_gap/1e6:.2f} million divide among families with children",
             fontsize=19,weight="bold",va="top",color="#24282b")
    fig.text(.07,.885,"Mean family net worth, millions of 2025 dollars · United States, 1989–2025",
             fontsize=11,color="#505659",va="top")
    ax.spines[["left","right","top","bottom"]].set_visible(False)
    ax.yaxis.tick_right();ax.yaxis.set_label_position("right")
    ax.grid(axis="y",color="#cdd0ce",linewidth=.7);ax.set_axisbelow(True)
    ax.set_ylim(0,2.75);ax.set_xlim(1988,2035)
    ax.set_xticks([1989,1995,2001,2007,2013,2019,2025])
    ax.set_yticks(np.arange(0,2.6,.5));ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f"{v:.1f}"))
    ax.tick_params(length=0,pad=7,labelsize=10,colors="#505659")
    for group,label,color in [("college","Bachelor’s degree\nor higher","#ba3a34"),
                               ("hs_or_less","High school/GED\nor less","#35576c")]:
        s=sub[sub.group==group].sort_values("year")
        ax.plot(s.year,s.estimate/1e6,color=color,linewidth=2.6,marker="o",markersize=4)
        last=s.iloc[-1]
        ax.text(2026.3,last.estimate/1e6,label+f"\n${last.estimate/1e6:.2f}m",fontsize=10,
                weight="bold",color=color,va="center",linespacing=1.35)
    ratio=gaps[(gaps["sample"]=="children_at_home") & (gaps.statistic=="mean") & (gaps.measure=="ratio")].set_index("year")
    fig.text(.07,.178,f"College/HS-or-less mean wealth: {ratio.loc[1989,'estimate']:.2f}× in 1989 → {ratio.loc[2025,'estimate']:.2f}× in 2025",
             fontsize=11,color="#24282b",weight="bold")
    fig.text(.07,.121,"Figure 4. Mean wealth by the reference person’s education, among families with resident children of any age.",fontsize=8.4,color="#505659")
    fig.text(.07,.089,"Survey-weighted; five implicates. Some college/associate degrees excluded. No additional inflation adjustment.",fontsize=8.4,color="#505659")
    fig.text(.07,.057,"Source: Federal Reserve Board, SCF public extracts. Point estimates; 95% intervals appear in Figure 1 and the data.",fontsize=8.4,color="#505659")
    directory.mkdir(parents=True,exist_ok=True)
    # Retain the intentional background in both exports.
    fig.savefig(directory/"figure_4_economist_style.png",dpi=450,facecolor=bg,
                metadata={"Software":"ps158-reproduce; Matplotlib"})
    fig.savefig(directory/"figure_4_economist_style.pdf",facecolor=bg,
                metadata={"CreationDate":FIXED_DATE,"ModDate":FIXED_DATE})
    plt.close(fig);print("Saved figure_4_economist_style.png and .pdf")
    style()


def sensitivity_chart(gaps,directory):
    fig=plt.figure(figsize=(10,7.3))
    for i,measure in enumerate(("absolute_gap","ratio")):
        ax=fig.add_axes([.105+i*.465,.365,.385,.575])
        sub=gaps[(gaps.statistic=="mean") & (gaps.measure==measure)]
        for sample,label,ls,marker in [("children_at_home","Children at home","-","o"),
                                         ("all_families","All families","--","s")]:
            s=sub[sub["sample"]==sample].sort_values("year")
            ax.plot(s.year,s.estimate/(1e6 if i==0 else 1),color="black",linestyle=ls,
                    marker=marker,markerfacecolor="black" if i==0 else "white",
                    markersize=4,linewidth=1.4,label=label)
        ax.set_ylim(0,2.5 if i==0 else 10);ax.set_xlim(1988,2026)
        ax.set_xticks([1989,2001,2013,2025]);ax.set_xlabel("SCF survey year")
        ax.spines[["top","right"]].set_visible(False);ax.grid(axis="y",color=".9",linewidth=.6)
        ax.set_axisbelow(True)
        ax.set_ylabel("Mean wealth gap (millions of 2025 dollars)" if i==0 else "Ratio of mean wealth (college / HS-or-less)")
        if i==0:ax.legend(frameon=False,loc="upper left",fontsize=9,handlelength=2.7)
    footer(fig,5,"Sample definition changes the measured wealth gap.",
        notes="Notes: Both panels compare bachelor’s-or-higher reference persons with high school/GED or less. "
        "Children at home means KIDS>0, including adult children; all families includes those without resident children. "
        "Survey-weighted means averaged over five implicates, in 2025 dollars. Lines show point estimates; confidence "
        "intervals for both samples are supplied in the processed CSV files. Ratios compare group means.")
    save(fig,"figure_5_sample_sensitivity",directory)


def course_median_chart(estimates,directory,data_dir):
    """Course-style companion using the stacked-file weighted medians.

    Main Figure 2 instead averages within-implicate medians and reports MI
    uncertainty. Both estimators are preserved; no values come from pixels.
    """
    sub=estimates[(estimates["sample"]=="children_at_home") &
                  (estimates.statistic=="median") & estimates.group.isin(["college","hs_or_less"])]
    values=sub.pivot(index="year",columns="group",values="pooled_five_implicates").sort_index()
    values.reset_index().to_csv(data_dir/"processed/course_figure_data.csv",index=False,float_format="%.17g")
    plt.rcParams.update({"font.family":"DejaVu Sans"})
    fig=plt.figure(figsize=(10,7.3));ax=fig.add_axes([.14,.25,.77,.55])
    fig.text(.065,.952,"Growing wealth gap",fontsize=19,weight="bold",va="top")
    fig.text(.065,.900,"Median net worth by parental education, in constant (2025) dollars, 1989–2025",fontsize=11,va="top")
    ax.axvspan(2014.5,2026,color=".95",zorder=0)
    ax.text(2014.9,687000,"Extension: 2016–2025",fontsize=8.7,color=".4",va="top")
    for group,label,color in [("college","BA or more",".1"),("hs_or_less","HS or less",".6")]:
        ax.plot(values.index,values[group],color=color,linewidth=2.3,label=label,solid_capstyle="round")
        last=values.loc[BASE,group]
        ax.annotate(f"${last/1000:.0f}K",xy=(BASE,last),xytext=(10,0),textcoords="offset points",
                    fontsize=9,color=".2",va="center",annotation_clip=False)
    ax.set_xlim(1988,2026);ax.set_ylim(0,700000)
    ax.set_xticks(values.index);ax.tick_params(labelsize=8.4)
    ax.yaxis.set_major_locator(MultipleLocator(100000))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x,p:f"${x:,.0f}"))
    ax.set_ylabel("Median family net worth",fontsize=11,weight="bold")
    ax.spines[["top","right"]].set_visible(False);ax.grid(axis="y",color=".87",linewidth=.6)
    ax.set_axisbelow(True);ax.legend(loc="upper left",frameon=True,fancybox=False,fontsize=10)
    fig.text(.065,.158,"Figure 6. Course-style median reproduction; weighted medians of the stacked five-implicate file.",fontsize=8.4)
    note=("Families with a child at home, including adult children; education of the SCF reference person. "
          "Some college/associate degrees excluded. Extracts already use 2025 dollars. This stacked-file "
          "estimator differs slightly from Figure 2’s average of within-implicate medians; Figure 2 supplies "
          "the multiple-imputation analysis and confidence intervals.")
    fig.text(.065,.119,textwrap.fill(note,133),fontsize=7.8,va="top",linespacing=1.35)
    fig.text(.065,.035,SOURCE,fontsize=8)
    save(fig,"figure_6_course_median",directory)
    style()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",type=Path,default=ROOT/"data")
    parser.add_argument("--figure-dir",type=Path,default=ROOT/"figures")
    parser.add_argument("--submission-figure",type=Path,default=ROOT/"figure.png",
                        help="Root-level copy of the featured median figure")
    args=parser.parse_args()
    e=pd.read_csv(args.data_dir/"processed/wealth_estimates.csv")
    g=pd.read_csv(args.data_dir/"processed/wealth_gaps.csv")
    if set(e.dollar_base)!={BASE} or set(e.year)!=set(range(1989,2026,3)):
        raise ValueError("Unexpected dollar base or missing survey wave")
    if e[["estimate","ci_low","ci_high"]].isna().any().any():
        raise ValueError("Incomplete estimates/uncertainty")
    style()
    group_chart(e,"mean",1,args.figure_dir)
    group_chart(e,"median",2,args.figure_dir)
    gap_chart(g,args.figure_dir)
    economist_chart(e,g,args.figure_dir)
    sensitivity_chart(g,args.figure_dir)
    course_median_chart(e,args.figure_dir,args.data_dir)
    args.submission_figure.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(args.figure_dir/"figure_2_median_wealth.png",args.submission_figure)
    print(f"Saved featured submission figure: {args.submission_figure}")


if __name__=="__main__":
    main()
