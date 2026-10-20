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
		kill -TERM -- -$$(cat $(PIDFILE)); \
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
