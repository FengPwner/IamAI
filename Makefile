.PHONY: help test write batch roster up down

help:  ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

test:  ## 跑测试（必须全绿）
	python3 -m pytest -q

write:  ## 千问只落一笔，看看写手干了什么
	python3 tools/writer_loop.py --once

batch:  ## 立刻打包提交一次
	python3 tools/commit_batch.py

roster:  ## 谁在写这个仓库、谁停了
	python3 tools/roster.py

up:  ## 起两个常驻写手进程
	bash tools/run_both.sh

down:  ## 停掉常驻写手进程
	bash tools/run_both.sh --stop