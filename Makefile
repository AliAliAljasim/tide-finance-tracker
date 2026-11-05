PYTHON  := .venv/bin/python
PIDFILE := .app.pid
LOGFILE := app.log
PORT    := 5000

.PHONY: start down restart logs status ollama

start:
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "Already running (pid $$(cat $(PIDFILE))) at http://127.0.0.1:$(PORT)"; \
	else \
		setsid sh -c 'echo $$$$ > $(PIDFILE); exec $(PYTHON) app.py' > $(LOGFILE) 2>&1 < /dev/null & \
		sleep 1; \
		echo "Started (pid $$(cat $(PIDFILE))) at http://127.0.0.1:$(PORT) - logs in $(LOGFILE)"; \
	fi

down:
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		kill -TERM -$$(cat $(PIDFILE)); \
		echo "Stopped (pid $$(cat $(PIDFILE)))"; \
	else \
		echo "Not running"; \
	fi
	@rm -f $(PIDFILE)

restart: down start

logs:
	@tail -f $(LOGFILE)

status:
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "Running (pid $$(cat $(PIDFILE))) at http://127.0.0.1:$(PORT)"; \
	else \
		echo "Not running"; \
	fi

# Local LLM used for statement parsing and categorization (see llm.py).
ollama:
	@if curl -sf http://127.0.0.1:11434/api/version >/dev/null; then \
		echo "Ollama already running"; \
	else \
		setsid ollama serve > $(HOME)/.ollama/serve.log 2>&1 < /dev/null & \
		sleep 2; \
		echo "Ollama started - logs in ~/.ollama/serve.log"; \
	fi

# ---- Demo -------------------------------------------------------------------
# The demo account's email lives in .demo.mk (not tracked), e.g.
#   DEMO_EMAIL := you@example.com
# or pass it directly: make demo DEMO_EMAIL=you@example.com
-include .demo.mk

OLLAMA_MODEL ?= qwen2.5:7b
OLLAMA_URL   := http://127.0.0.1:11434

.PHONY: demo unload check-demo-email

check-demo-email:
	@if [ -z "$(DEMO_EMAIL)" ]; then \
		echo "Set DEMO_EMAIL in .demo.mk or run: make $(MAKECMDGOALS) DEMO_EMAIL=you@example.com"; \
		exit 1; \
	fi

# Sample data in, AI model loaded and kept warm, app running.
# The app is stopped while seeding: it keeps the data file in memory and
# would overwrite changes made underneath it.
demo: check-demo-email ollama
	@$(MAKE) --no-print-directory down
	@OLLAMA_HOST= $(PYTHON) scripts/seed_demo_data.py --email $(DEMO_EMAIL)
	@echo "Loading $(OLLAMA_MODEL) (the first load can take a minute or two)..."
	@curl -sf $(OLLAMA_URL)/api/generate -d '{"model":"$(OLLAMA_MODEL)","keep_alive":"3h"}' >/dev/null \
		&& echo "Model loaded and kept in memory for 3 hours" \
		|| echo "Could not load the model - is Ollama installed? (the app still works without the assistant)"
	@$(MAKE) --no-print-directory start
	@echo "Demo ready"

# Back to normal: sample data removed, model unloaded from memory, app running.
unload: check-demo-email
	@$(MAKE) --no-print-directory down
	@OLLAMA_HOST= $(PYTHON) scripts/seed_demo_data.py --email $(DEMO_EMAIL) --remove
	@if curl -sf $(OLLAMA_URL)/api/version >/dev/null; then \
		curl -sf $(OLLAMA_URL)/api/generate -d '{"model":"$(OLLAMA_MODEL)","keep_alive":0}' >/dev/null \
			&& echo "Model unloaded from memory"; \
	fi
	@$(MAKE) --no-print-directory start
	@echo "Back to normal"
