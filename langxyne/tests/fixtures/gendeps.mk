# The including makefile test_cli_gendeps.py's GendepsMake runs `make -n` over: the gendeps fragment
# frag.mk beside it, then each GENERATED target printed.
GEN := OUTDIR
BASE := xy
LANGXYNE := /pkg
include frag.mk
all: $(GENERATED)
	@echo $(foreach t,$(GENERATED),target=$(t))
