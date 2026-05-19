SHELL := /bin/zsh
UV ?= /Users/vox/.local/bin/uv
BACKUP_DIR ?= backups
OUTPUT_FORMAT ?= both
MAX_AGE_MINUTES ?= 60
CRON_LOG ?= /Users/vox/lib/logs/snapshot.log

.PHONY: help snapshot snapshot-if-stale cron-line install-cron uninstall-cron install-cron-test uninstall-cron-test

help:
	@printf "Targets:\n"
	@printf "  make snapshot             Run full base snapshot now\n"
	@printf "  make snapshot-if-stale    Snapshot only if older than threshold\n"
	@printf "  make cron-line            Print hourly cron line\n"
	@printf "  make install-cron         Install hourly stale-check cron\n"
	@printf "  make uninstall-cron       Remove hourly stale-check cron\n"
	@printf "  make install-cron-test    Install 1-minute test cron (forced run)\n"
	@printf "  make uninstall-cron-test  Remove 1-minute test cron\n"

snapshot:
	$(UV) run lib2k26 snapshot-base --backup-dir "$(BACKUP_DIR)" --output-format "$(OUTPUT_FORMAT)"

snapshot-if-stale:
	$(UV) run lib2k26 snapshot-base-if-stale --backup-dir "$(BACKUP_DIR)" --output-format "$(OUTPUT_FORMAT)" --max-age-minutes "$(MAX_AGE_MINUTES)"

cron-line:
	@mkdir -p "$(dir $(CRON_LOG))"
	@printf '0 * * * * cd /Users/vox/lib && $(UV) run lib2k26 snapshot-base-if-stale --backup-dir "$(BACKUP_DIR)" --output-format "$(OUTPUT_FORMAT)" --max-age-minutes "$(MAX_AGE_MINUTES)" >> "$(CRON_LOG)" 2>&1\n'

install-cron:
	@mkdir -p "$(dir $(CRON_LOG))"
	@(crontab -l 2>/dev/null; printf '0 * * * * cd /Users/vox/lib && $(UV) run lib2k26 snapshot-base-if-stale --backup-dir "$(BACKUP_DIR)" --output-format "$(OUTPUT_FORMAT)" --max-age-minutes "$(MAX_AGE_MINUTES)" >> "$(CRON_LOG)" 2>&1\n') | crontab -
	@echo "Installed hourly snapshot cron job."

uninstall-cron:
	@tmpfile=$$(mktemp); \
	crontab -l 2>/dev/null | grep -v 'lib2k26 snapshot-base-if-stale' > $$tmpfile || true; \
	crontab $$tmpfile; \
	rm -f $$tmpfile; \
	echo "Removed lib2k26 snapshot cron job (if present)."

install-cron-test:
	@mkdir -p "$(dir $(CRON_LOG))"
	@(crontab -l 2>/dev/null; printf '* * * * * cd /Users/vox/lib && $(UV) run lib2k26 snapshot-base-if-stale --backup-dir "$(BACKUP_DIR)" --output-format "$(OUTPUT_FORMAT)" --max-age-minutes "0" >> "$(CRON_LOG)" 2>&1\n') | crontab -
	@echo "Installed 1-minute test cron job (forced snapshot run)."

uninstall-cron-test:
	@tmpfile=$$(mktemp); \
	crontab -l 2>/dev/null | grep -v '\* \* \* \* \* cd /Users/vox/lib && .*lib2k26 snapshot-base-if-stale.*--max-age-minutes "0"' > $$tmpfile || true; \
	crontab $$tmpfile; \
	rm -f $$tmpfile; \
	echo "Removed 1-minute test cron job (if present)."
