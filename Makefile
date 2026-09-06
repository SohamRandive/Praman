.PHONY: help data validate verify-matrix test lint demo draft system diagram trace eval console console-data console-metrics chamber-data clean check-attribution

SEED ?= 20260904
CORPUS ?= data/corpus
COST ?= 35000   # contest cost in paise. A merchant input, not a constant.

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

data:  ## regenerate the corpus bit-identically from SEED
	cd data/generator && python3 build.py --out ../../$(CORPUS) --seed $(SEED)

validate:  ## print archetype distributions and corpus self-checks
	cd data/generator && python3 archetypes.py
	python3 -m eval.validate_corpus --corpus $(CORPUS)

verify-matrix:  ## fail if the matrix has not been checked against the live docs recently
	python3 -c "import sys; from praman.evidence import ReasonCodeMatrix as M; \
p=M.load().verification_problems(); \
print('matrix verification: ' + ('; '.join(p) if p else 'current')); sys.exit(1 if p else 0)"

test:  ## unit tests
	python3 -m pytest tests -q

lint:  ## static checks
	python3 -m ruff check praman data tests eval || true

console-data:  ## decide real cases and dump them for the console
	python3 -m praman.console.fixtures --corpus $(CORPUS)

console-metrics:  ## write the KPI numbers the console reads (a slice of `make eval`)
	python3 -m eval.run_eval --corpus $(CORPUS) --cost-minor $(COST) --no-figures \
		--metrics-out web/src/metrics.json

chamber-data:  ## export the entity graph for the network chamber
	python3 -m praman.console.chamber --corpus $(CORPUS)

console:  ## build the console (needs `npm install` in web/ first)
	cd web && npm run build

system:  ## latency, per-agent degradation, model calls per case
	python3 -m eval.system_metrics --corpus $(CORPUS)

draft:  ## draft representments and show the grounding verifier working
	python3 -m praman.drafting --corpus $(CORPUS)

demo:  ## walk real corpus cases through the evidence engine
	python3 -m praman.demo --corpus $(CORPUS)

trace:  ## trace one case through every engine stage, live
	python3 -m praman.trace

eval:  ## full metrics table, three baselines, ablations, figures
	python3 -m eval.run_eval --corpus $(CORPUS) --cost-minor $(COST)

# `git grep -E` is POSIX ERE and silently ignores \b, so this pattern carries no
# word boundaries and must not need any. None of these four collide with ordinary
# vocabulary; bare `cursor` does - a scan position, a CSS property - so it is
# reachable only as `.cursor` or `cursorrules`. A guard that cries wolf gets
# disabled, and one that matches nothing is worse: it reports clean forever.
ATTRIB = anthropic|openai|copilot|co-authored-by|generated with|\.cursor|cursorrules
GUARDS = ':!Makefile' ':!.gitignore' ':!.github/workflows/ci.yml' \
         ':!tests/test_scope_invariants.py' ':!tests/test_corpus.py'

check-attribution:  ## fail if any vendor or assistant attribution reached the repo
	@! git log --format='%an <%ae>%n%b' 2>/dev/null | grep -i -E '$(ATTRIB)' \
		|| (echo "FAIL: attribution in git history"; exit 1)
	@! git grep --untracked -i -n -E '$(ATTRIB)' \
		-- ':!*.lock' ':!package-lock.json' $(GUARDS) \
		|| (echo "FAIL: vendor name in tree"; exit 1)
	@echo "clean: no attribution in history or tree"

diagram:  ## re-export the architecture diagram from the README mermaid block
	@mkdir -p docs/figures
	python3 -m eval.export_diagram
	npx -y @mermaid-js/mermaid-cli -i docs/figures/architecture.mmd \
		-o docs/figures/architecture.png -b white -w 1600
	@echo "docs/figures/architecture.png regenerated from the README"

clean:
	rm -rf $(CORPUS)/* eval/figures/*.png
	find . -name __pycache__ -type d -exec rm -rf {} +
