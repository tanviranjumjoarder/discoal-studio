import csv, math, os, random, subprocess

DISCOAL = "discoal_latest/discoal"
OUT = "discoal_data"
PER_CLASS = 3000                 # files per class
L = 1_100_000                    # region length in bp = number of sites (1.1 Mb)
N_HAP = 198                      # haplotypes, 99 CEU individuals x 2


def g(v):
    return f"{v:.10g}"           # a number written with 10 significant digits


for kind in ["neutral", "sweep"]:
    os.makedirs(os.path.join(OUT, kind.capitalize()), exist_ok=True)
    rows = []
    for i in range(1, PER_CLASS + 1):
        rng = random.Random(f"20261001-{kind}-{i}")   # this file's own random numbers, same every run
        N = rng.randint(5000, 30000)                  # population size
        mu = rng.uniform(2.21e-9, 2.21e-8)            # mutation rate per bp per generation
        r = rng.expovariate(1 / 1e-8)                 # recombination rate, exponential with mean 1e-8
        while r > 3e-8:                               # above 3 x mean: draw again
            r = rng.expovariate(1 / 1e-8)
        row = dict(file=f"{kind}_{i}.ms", N=N, mu=mu, r=r, s=0, theta=4 * N * mu * L, rho=4 * N * r * L)
        sweep = []
        if kind == "sweep":
            s = math.exp(rng.uniform(math.log(0.005), math.log(0.1)))           # log-uniform 0.005 to 0.1
            f0 = math.exp(rng.uniform(math.log(1 / (2 * N)), math.log(0.2)))   # log-uniform 1/(2N) to 0.2
            tau = 0                                                             # generations since the sweep finished
            row.update(s=s, f0=f0, tau=tau, alpha=2 * N * s)
            sweep = ["-ws", g(tau / (4 * N)), "-a", g(2 * N * s), "-f", g(f0), "-x", "0.5"]
        row["seed1"], row["seed2"] = rng.randint(1, 2_000_000_000), rng.randint(1, 2_000_000_000)
        cmd = ["discoal", str(N_HAP), "1", str(L), "-t", g(row["theta"]), "-r", g(row["rho"]),
               "-d", str(row["seed1"]), str(row["seed2"])] + sweep
        row["command"] = " ".join(cmd)
        with open(os.path.join(OUT, kind.capitalize(), row["file"]), "w") as fh:
            subprocess.run(cmd, executable=DISCOAL, stdout=fh, check=True)   # = discoal ... > file
        rows.append(row)
    with open(os.path.join(OUT, f"params_{kind}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
