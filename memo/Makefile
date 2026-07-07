PDFLATEX ?= /scratch/projects/tacc/texlive/2025/bin/x86_64-linux/pdflatex
LATEXFLAGS ?= -interaction=nonstopmode
TEX = ngvla_sa_selection.tex
PDF = ngvla_sa_selection.pdf

.PHONY: pdf test clean

pdf:
	$(PDFLATEX) $(LATEXFLAGS) $(TEX)
	$(PDFLATEX) $(LATEXFLAGS) $(TEX)

test: pdf

clean:
	rm -f $(PDF) *.aux *.log *.out *.toc *.bbl *.blg *.fls *.fdb_latexmk *.synctex.gz
