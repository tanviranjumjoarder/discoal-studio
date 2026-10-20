# Authorship, licensing and citation

This note explains what protects your authorship of discoal Studio, what does not,
and why. It is general information, not legal advice; for a binding answer, ask
FAU's technology transfer office or an IP lawyer.

## What you already have

- **Copyright, automatically.** You own the copyright in the code you wrote from the
  moment you wrote it. No registration is needed. The copyright line
  (`Copyright (C) 2026 Tanvir Anjum Joarder`) is now at the top of every source file,
  in `NOTICE`, in the app's header, footer and *About & cite* dialog, and in
  `CITATION.cff`. In the US you can also register the copyright with the US Copyright
  Office (about $45–65 online). That is optional, but it is needed before suing for
  infringement.
- **An attribution requirement in the license.** discoal is GPL-3.0, so anything that
  ships it must be GPL too. GPLv3 section 7(b) lets an author add one kind of extra
  term: keeping author attributions. `NOTICE` uses it. Anyone who shares the app or a
  changed version must keep your name in the source, in the interface and in the
  outputs, and must mark changed versions as changed.
- **A permanent public record of authorship and date.** Git history, a GitHub release,
  and a Zenodo DOI (below) give a timestamped, citable record that the app is yours.

## What the license cannot do

The GPL does not allow terms such as "ask me for permission before using it" or
"non-commercial use only". Adding them would break discoal's license, and then the app
could not be distributed at all. So:

- **Using** the app needs no permission (GPL).
- **Keeping your name** on copies and changed versions is required (NOTICE, GPLv3 §7(b)).
- **Citing** it in papers is a request. It is enforced by academic norms (and journal
  policies on software citation), not by the license. Make it easy: `CITATION.cff`,
  the *About & cite* dialog, `discoal-studio cite`, and the citation text in every
  `manifest.json`, SLURM script and `.npz` file.
- **Forking on GitHub** keeps your commits and authorship in the fork's history. That
  is the normal way others build on it, and the README asks for it.

## Why not a patent

- A patent protects an invention: a new, non-obvious technical method. It does not
  protect authorship. A GUI that builds discoal command lines from physical units is
  unlikely to clear the non-obviousness bar, and US courts often reject patents on
  software that automates a known calculation (*Alice v. CLS Bank*, 2014).
- It is expensive (typically $10,000+ in attorney and USPTO fees) and slow (2–3 years).
- Public disclosure starts a clock. In the US you have one year after first public
  disclosure (a public GitHub repo, a talk, a preprint) to file. Most other countries
  allow no grace period at all.
- GPLv3 section 11 gives every user a free license to any patent you hold on the
  program, so a patent could not restrict users of this app anyway.
- As a university student, check FAU's IP policy: work made with university resources
  may have to be disclosed to the university first.

What gives you credit in research is a citable publication.

## Recommended steps

1. Push the repository to GitHub under your account (keep `NOTICE`, `LICENSE`,
   `CITATION.cff`). GitHub then shows a "Cite this repository" button.
2. Connect the repository to Zenodo (zenodo.org → GitHub → enable the repo) and
   publish a release (e.g. `v0.2.0`). Zenodo reads `.zenodo.json` and gives the release
   a DOI. Add that DOI to `CITATION.cff` and the README.
3. Submit a short software paper to the Journal of Open Source Software (JOSS) or an
   application note to *Bioinformatics*. Once it is published, people cite the paper,
   and it counts on your CV and Google Scholar.
4. Prior art. As of October 2026, a search found no other graphical app or dataset
   generator for discoal; discoal itself is command-line only. Mention this, with the
   date of the search, in the paper's "statement of need".
