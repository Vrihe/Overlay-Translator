# Thin wrapper over training/pipeline.py for Linux, WSL and the training Docker image.
# On Windows without make, call the pipeline directly:
#   .venv-train\Scripts\python training/pipeline.py all --config configs/train/v2.yaml
#
#   make all CONFIG=configs/train/v2.yaml NAME=v2-repro
#   make train CONFIG=configs/train/v1.yaml NAME=v1-repro ARGS=--dry-run

PYTHON ?= python
CONFIG ?= configs/train/v2.yaml
NAME ?=
ARGS ?=

PIPELINE = $(PYTHON) training/pipeline.py
OPTS = --config $(CONFIG) $(if $(NAME),--name $(NAME)) $(ARGS)

.PHONY: all data train merge convert eval

all data train merge convert eval:
	$(PIPELINE) $@ $(OPTS)
